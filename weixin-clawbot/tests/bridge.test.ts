/**
 * Tests for the pure pieces of the bridge: SSE decoding, approval parsing, tool
 * previews, and reply spilling.
 *
 * The Nova-facing HTTP client is exercised against a real `nova serve` by
 * `scripts/smoke.ts`; here everything is dependency-injected so the interesting
 * logic runs without a server or a WeChat login.
 */

import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import {
  decodeSse,
  frameData,
  frameDataString,
  frameString,
  describeToolCall,
  type NovaFrame,
} from "../src/nova.js";
import { ApprovalRegistry, parseApprovalReply } from "../src/approvals.js";
import { ProgressReporter, type SendFn } from "../src/reporter.js";
import { SessionStore } from "../src/sessions.js";

/** Build an SSE body from raw text so parser edge cases stay visible. */
function sseBody(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

/** Drain a decoder into a plain array. */
async function collect(
  stream: ReadableStream<Uint8Array>,
): Promise<readonly NovaFrame[]> {
  const frames: NovaFrame[] = [];
  for await (const frame of decodeSse(stream)) {
    frames.push(frame);
  }
  return frames;
}

describe("SSE frame decoding", () => {
  it("decodes data frames and sequence prefixes", async () => {
    const frames = await collect(
      sseBody([
        'id: 1\ndata: {"type":"data-nova-session","data":{"sessionId":"s1"}}\n\n',
        'id: 2\ndata: {"type":"text-delta","delta":"hi"}\n\n',
      ]),
    );
    assert.equal(frames.length, 2);
    assert.deepEqual(frames[0], {
      type: "data-nova-session",
      sequence: 1,
      payload: { type: "data-nova-session", data: { sessionId: "s1" } },
    });
    assert.equal(frameString(frames[1]!, "delta"), "hi");
  });

  it("ignores pings and the DONE sentinel", async () => {
    const frames = await collect(
      sseBody([
        ":ping\n\n",
        'data: {"type":"text-delta","delta":"a"}\n\n',
        "data: [DONE]\n\n",
        'data: {"type":"text-delta","delta":"never"}\n\n',
      ]),
    );
    assert.equal(frames.length, 1);
    assert.equal(frameString(frames[0]!, "delta"), "a");
  });

  it("reassembles frames split across chunk boundaries", async () => {
    const frames = await collect(
      sseBody([
        'id: 1\ndata: {"type":"text-del',
        'ta","delta":"split"}\n',
        "\n",
      ]),
    );
    assert.equal(frames.length, 1);
    assert.equal(frameString(frames[0]!, "delta"), "split");
  });

  it("drops malformed payloads instead of throwing", async () => {
    const frames = await collect(
      sseBody([
        "data: {not json}\n\n",
        'data: {"noType":1}\n\n',
        'data: [1,2,3]\n\n',
        'data: {"type":"finish"}\n\n',
      ]),
    );
    assert.equal(frames.length, 1);
    assert.equal(frames[0]!.type, "finish");
  });

  it("tolerates CRLF line endings and a missing trailing blank line", async () => {
    const frames = await collect(
      sseBody(['id: 3\r\ndata: {"type":"finish"}\r\n']),
    );
    assert.equal(frames.length, 1);
    assert.equal(frames[0]!.sequence, 3);
  });
});

describe("describeToolCall", () => {
  it("shows a shell command in full, and nothing else", () => {
    const summary = describeToolCall("shell", {
      command: "ls -la /tmp && echo done",
      timeout: 30,
      description: "list",
    });
    assert.equal(summary, "ls -la /tmp && echo done");
  });

  it("keeps a long shell command readable rather than dumping it whole", () => {
    const summary = describeToolCall("shell", {
      command: "x".repeat(400),
      timeout: 30,
    });
    assert.equal(summary.length, 120);
    assert.ok(summary.endsWith("…"));
  });

  it("finds the path in read, edit and write, which spell it filePath", () => {
    for (const tool of ["read", "edit", "write"]) {
      const summary = describeToolCall(tool, {
        filePath: "/srv/app/main.py",
        offset: 1,
        limit: 200,
      });
      assert.equal(summary, "/srv/app/main.py", tool);
    }
  });

  it("finds the path in read_image, which spells it file_path", () => {
    // The three spellings are the whole reason a single-key lookup fails.
    assert.equal(
      describeToolCall("read_image", { file_path: "/tmp/shot.png" }),
      "/tmp/shot.png",
    );
  });

  it("never leaks file contents for edit or write", () => {
    const edit = describeToolCall("edit", {
      filePath: "/srv/a.py",
      oldString: "SECRET_TOKEN = 'hunter2'",
      newString: "SECRET_TOKEN = 'new'",
    });
    assert.equal(edit, "/srv/a.py");
    assert.ok(!edit.includes("hunter2"));

    const write = describeToolCall("write", {
      content: "SECRET_TOKEN = 'hunter2'",
      filePath: "/srv/a.py",
    });
    assert.equal(write, "/srv/a.py");
    assert.ok(!write.includes("hunter2"));
  });

  it("drops the offset and limit noise that buried the path", () => {
    const summary = describeToolCall("read", {
      filePath: "README.md",
      offset: 1,
      limit: 1,
    });
    assert.equal(summary, "README.md");
  });

  it("reads glob and grep as pattern in directory", () => {
    assert.equal(
      describeToolCall("grep", { pattern: "*.py", path: ".", include: "*.py" }),
      "*.py in .",
    );
    assert.equal(describeToolCall("glob", { pattern: "**/*.ts" }), "**/*.ts");
  });

  it("names the argument each remaining tool acts on", () => {
    assert.equal(describeToolCall("web_search", { query: "nova agent", limit: 8 }), "nova agent");
    assert.equal(describeToolCall("web_fetch", { url: "https://x.dev", timeout: 20 }), "https://x.dev");
    assert.equal(describeToolCall("delegate_to_agent", { target: "explore", task: "find", context: "c" }), "explore");
    assert.equal(describeToolCall("subagent_status", { target: "explore" }), "explore");
    assert.equal(describeToolCall("browser_use", { action: "click #btn" }), "click #btn");
    assert.equal(describeToolCall("background_task_logs", { task_id: "task-7" }), "task-7");
  });

  it("never prints stored memory or skill content", () => {
    // save_memory carries `content`; the fallback would have dumped the first two
    // scalars, which is the memory body. Listing the tool keeps it to the key.
    const save = describeToolCall("save_memory", {
      key: "user.timezone",
      content: "Asia/Shanghai",
      summary: "tz",
    });
    assert.equal(save, "user.timezone");
    assert.ok(!save.includes("Shanghai"));

    assert.equal(describeToolCall("search_memory", { query: "timezone", limit: 5 }), "timezone");
    assert.equal(describeToolCall("delete_memory", { key: "old.note" }), "old.note");
    assert.equal(describeToolCall("load_skill", { skill_name: "pdf" }), "pdf");
    assert.equal(describeToolCall("install_skill", { skill_ref: "owner/repo", force: true }), "owner/repo");
  });

  it("says nothing for tools that only take bulk or no arguments", () => {
    // An argument-less or array-only tool has nothing worth a chat line beyond
    // its own name, and the fallback would be noise.
    assert.equal(describeToolCall("todo_write", { todos: [{ content: "x", status: "pending" }] }), "");
    assert.equal(describeToolCall("ask_user", { questions: [{ question: "q" }] }), "");
    assert.equal(describeToolCall("list_skills", {}), "");
    assert.equal(describeToolCall("background_task_list", {}), "");
  });

  it("does not claim tools Nova does not have", () => {
    // Nova exposes `edit`, never a separate multi-file edit tool, so `multiedit`
    // is not in the table. It still renders sensibly, via the conventional
    // `filePath` name rather than a fabricated table entry.
    assert.equal(describeToolCall("multiedit", { filePath: "/a.py" }), "/a.py");
    assert.equal(
      describeToolCall("multiedit", { filePath: "/a.py" }),
      describeToolCall("edit", { filePath: "/a.py" }),
    );
  });

  it("identifies an unknown tool's argument by conventional name", () => {
    // The MCP case: arbitrary schemas, but the argument that carries intent
    // still tends to be one of these names.
    assert.equal(
      describeToolCall("mcp_search", { query: "how to center a div" }),
      "how to center a div",
    );
    assert.equal(describeToolCall("mcp_read", { path: "/srv/app/main.py" }), "/srv/app/main.py");
    assert.equal(describeToolCall("mcp_exec", { command: "docker ps -a" }), "docker ps -a");
    assert.equal(describeToolCall("mcp_write", { text: "hello" }), "hello");
    assert.equal(describeToolCall("mcp_named", { name: "report.pdf" }), "report.pdf");
  });

  it("lets a conventional argument win over numeric noise", () => {
    // `{timeout:300, command:"..."}` previously led with the timeout and buried
    // the command, which is the exact failure the listed-tool path was fixed for.
    const summary = describeToolCall("some_new_tool", {
      timeout: 300,
      command: "npm run build",
    });
    assert.equal(summary, "npm run build");
    assert.ok(!summary.includes("timeout"));
  });

  it("shows a lone unrecognised string argument, since MCP tools often take one", () => {
    assert.equal(describeToolCall("odd_tool", { whatever: "payload" }), "payload");
  });

  it("stays silent rather than guessing between unrecognised strings", () => {
    // Key order would be the only thing deciding what the user sees, so a bare
    // tool name beats an invented detail.
    assert.equal(describeToolCall("mystery_tool", { alpha: "one", beta: "two" }), "");
    assert.equal(describeToolCall("positional", { a: "x", b: "y", c: "z" }), "");
  });

  it("shows nothing for an unknown tool with only numbers or structures", () => {
    assert.equal(describeToolCall("noisy_tool", { verbose: true, retries: 2, depth: 3 }), "");
    assert.equal(describeToolCall("bulky_tool", { items: [1, 2], filter: { a: 1 } }), "");
    assert.equal(describeToolCall("scalars_only", { count: 5 }), "");
  });

  it("returns empty when there is nothing renderable", () => {
    assert.equal(describeToolCall("todo_write", { todos: [{ content: "x" }] }), "");
    assert.equal(describeToolCall("read", { offset: 3 }), "");
    assert.equal(describeToolCall("read", null), "");
    assert.equal(describeToolCall("read", 42), "");
  });

  it("accepts a bare string input", () => {
    assert.equal(describeToolCall("shell", "echo hi"), "echo hi");
  });
});

describe("parseApprovalReply", () => {
  it("accepts the documented affirmative forms", () => {
    for (const text of ["y", "Y", "yes", "好", "可以", "同意", " ok "]) {
      assert.deepEqual(parseApprovalReply(text), {
        approved: true,
        remember: false,
      });
    }
  });

  it("treats 'a' as allow-and-remember", () => {
    assert.deepEqual(parseApprovalReply("a"), { approved: true, remember: true });
    assert.deepEqual(parseApprovalReply("总是"), {
      approved: true,
      remember: true,
    });
  });

  it("accepts the documented negative forms", () => {
    for (const text of ["n", "no", "否", "拒绝", "取消"]) {
      assert.deepEqual(parseApprovalReply(text), {
        approved: false,
        remember: false,
      });
    }
  });

  it("returns null for anything else", () => {
    assert.equal(parseApprovalReply("继续跑"), null);
    assert.equal(parseApprovalReply(""), null);
  });
});

describe("ApprovalRegistry", () => {
  const approval = {
    requestId: "req1",
    sessionId: "s1",
    command: "rm -rf /tmp/x",
    description: "删除目录",
  };

  it("hands out a pending request exactly once", () => {
    const registry = new ApprovalRegistry();
    assert.equal(registry.has("c1"), false);
    registry.open("c1", approval);
    assert.equal(registry.has("c1"), true);
    assert.deepEqual(registry.take("c1"), approval);
    assert.equal(registry.has("c1"), false);
    assert.equal(registry.take("c1"), undefined);
  });

  it("clears without answering", () => {
    const registry = new ApprovalRegistry();
    registry.open("c1", approval);
    registry.clear("c1");
    assert.equal(registry.has("c1"), false);
  });

  it("renders the command and the answer key in the prompt", () => {
    const prompt = ApprovalRegistry.describe(approval);
    assert.match(prompt, /rm -rf \/tmp\/x/);
    assert.match(prompt, /删除目录/);
    assert.match(prompt, /y/);
    assert.match(prompt, /n/);
  });
});

describe("ProgressReporter", () => {
  /** Record every bubble the reporter sends. */
  function recorder(): { sent: string[]; send: SendFn } {
    const sent: string[] = [];
    return {
      sent,
      send: async (message) => {
        assert.equal(typeof message, "string");
        sent.push(message as string);
      },
    };
  }

  const options = {
    intervalMs: 5,
    maxTextChars: 200,
    spillDir: join(tmpdir(), "nova-progress-test"),
    label: "conv",
  };

  it("batches notes into a single bubble", async () => {
    const { sent, send } = recorder();
    const reporter = new ProgressReporter(send, options);
    reporter.note("→ shell ls");
    reporter.note("→ grep *.py");
    await reporter.close();
    assert.equal(sent.length, 1);
    assert.equal(sent[0], "→ shell ls\n→ grep *.py");
  });

  it("drops empty and consecutive duplicate notes", async () => {
    const { sent, send } = recorder();
    const reporter = new ProgressReporter(send, options);
    reporter.note("  ");
    reporter.note("→ shell ls");
    reporter.note("→ shell ls");
    await reporter.close();
    assert.equal(sent.length, 1);
    assert.equal(sent[0], "→ shell ls");
  });

  it("sends a short reply verbatim", async () => {
    const { sent, send } = recorder();
    const reporter = new ProgressReporter(send, options);
    await reporter.reply("done");
    assert.deepEqual(sent, ["done"]);
  });

  it("spills an over-long reply into a file attachment", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-spill-"));
    const sent: unknown[] = [];
    const reporter = new ProgressReporter(
      async (message) => {
        sent.push(message);
      },
      { ...options, spillDir: dir, maxTextChars: 50 },
    );
    const body = "y".repeat(500);
    await reporter.reply(body);

    assert.equal(sent.length, 1);
    const message = sent[0] as { text: string; media: { fileName: string; url: string } };
    assert.ok(message.text.length < body.length);
    assert.match(message.text, /全文见附件/);
    assert.equal(await readFile(message.media.url, "utf8"), body);
  });

  it("stops queueing after close", async () => {
    const { sent, send } = recorder();
    const reporter = new ProgressReporter(send, options);
    await reporter.close();
    reporter.note("late");
    assert.deepEqual(sent, []);
  });
});

describe("SessionStore", () => {
  it("persists bindings across instances", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-sessions-"));
    const statePath = join(dir, "nested", "sessions.json");

    const first = new SessionStore(statePath);
    await first.load();
    await first.bind("conv1", "sess1");

    const second = new SessionStore(statePath);
    await second.load();
    assert.equal(second.sessionFor("conv1"), "sess1");
  });

  it("resolves a namespaced key after a reload", async () => {
    // The store is keyed by `<agentKey>/<conversationId>` because one file holds
    // one agent but a bridge may still be asked about others. The namespace is
    // part of the key and must survive a load untouched: an earlier version
    // stripped it as a legacy leftover, which silently unresolvable every
    // session on the first restart after upgrading.
    const dir = await mkdtemp(join(tmpdir(), "nova-sessions-ns-"));
    const statePath = join(dir, "sessions.writing-coach.json");

    const first = new SessionStore(statePath);
    await first.load();
    await first.bind("writing-coach/user-1", "sess-1");

    const second = new SessionStore(statePath);
    await second.load();
    assert.equal(second.sessionFor("writing-coach/user-1"), "sess-1");
    assert.equal(
      second.sessionFor("user-1"),
      undefined,
      "the bare id must not resolve; the namespace is the point",
    );
  });

  it("starts empty when the state file is absent", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-sessions-"));
    const store = new SessionStore(join(dir, "missing.json"));
    await store.load();
    assert.equal(store.sessionFor("conv1"), undefined);
  });

  it("ignores malformed state instead of throwing", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-sessions-"));
    const statePath = join(dir, "sessions.json");
    const { writeFile } = await import("node:fs/promises");
    await writeFile(statePath, "{not json", "utf8");

    const store = new SessionStore(statePath);
    await store.load();
    assert.equal(store.sessionFor("conv1"), undefined);
  });

  it("forgets a binding but leaves an unrelated one intact", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-sessions-"));
    const store = new SessionStore(join(dir, "sessions.json"));
    await store.load();
    await store.bind("c1", "s1");
    await store.bind("c2", "s2");
    await store.forget("c1");
    assert.equal(store.sessionFor("c1"), undefined);
    assert.equal(store.sessionFor("c2"), "s2");
  });

  it("refuses to bind before load", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-sessions-"));
    const store = new SessionStore(join(dir, "sessions.json"));
    await assert.rejects(() => store.bind("c1", "s1"), /load\(\)/);
  });
});

describe("frame accessors", () => {
  const approval: NovaFrame = {
    type: "data-nova-approval-required",
    sequence: 7,
    payload: {
      type: "data-nova-approval-required",
      data: { requestId: "r1", command: "ls" },
    },
  };
  const standard: NovaFrame = {
    type: "text-delta",
    sequence: 8,
    payload: { type: "text-delta", id: "text_1", delta: "hi" },
  };

  it("reads top-level string fields, defaulting to empty", () => {
    assert.equal(frameString(standard, "delta"), "hi");
    assert.equal(frameString(standard, "missing"), "");
    assert.equal(frameString({ ...standard, payload: {} }, "missing"), "");
  });

  it("reads data-nova-* fields only from the data sub-object", () => {
    // Nova nests data-nova-* fields under `data`; reading them off the top
    // level silently yields "" and loses the session id.
    assert.equal(frameDataString(approval, "requestId"), "r1");
    assert.equal(frameDataString(approval, "command"), "ls");
    assert.equal(frameString(approval, "requestId"), "");
  });

  it("returns an empty record when data is absent or not a record", () => {
    assert.deepEqual(frameData(approval), { requestId: "r1", command: "ls" });
    assert.deepEqual(frameData({ ...approval, payload: { data: 5 } }), {});
    assert.deepEqual(frameData({ ...approval, payload: { data: [] } }), {});
    assert.deepEqual(frameData(standard), {});
  });
});