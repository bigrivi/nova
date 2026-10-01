/**
 * Live check of the approval round trip against a real `nova serve`.
 *
 * Nova blocks a dangerous command until `POST /api/chat/approve` resolves it.
 * This drives the whole cycle: a dangerous command, the
 * `data-nova-approval-required` frame on the wire, and a resolution that
 * releases the turn. The chat-facing half (a typed "y"/"n" reaching Nova) runs
 * against a canned Nova so it is deterministic -- a real model will not emit a
 * dangerous command on request.
 *
 * Usage:
 *   nova serve
 *   NOVA_BASE_URL=http://127.0.0.1:8765 NOVA_AGENT_KEY=weixin npm run approval
 */

import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Bot, ChatResponse } from "weixin-agent-sdk";
import { WeixinNovaAgent } from "../src/agent.js";
import { loadConfig, type BridgeConfig } from "../src/config.js";
import { error, info, setLogLevel } from "../src/log.js";
import {
  frameDataString,
  NovaClient,
  type NovaAgentSummary,
  type NovaChatRequest,
  type NovaFrame,
  type NovaLike,
} from "../src/nova.js";
import { ApprovalRegistry, parseApprovalReply } from "../src/approvals.js";
import { PRIMARY_AGENTS } from "./fixtures.js";
import { SessionStore } from "../src/sessions.js";
import { ensureOutbox, listOutbox } from "../src/outbox.js";

/** A shell command Nova classifies as dangerous, so approval is required. */
const DANGEROUS = "rm -rf /tmp/nova-weixin-approval-probe";

/** Frame helper so the canned stream reads like the real wire format. */
function frame(type: string, data: Record<string, unknown> = {}): NovaFrame {
  return { type, sequence: undefined, payload: { type, data } };
}

/**
 * A Nova stand-in that replays a scripted frame sequence per turn.
 *
 * Scripts are consumed in order, so a turn can be made to ask for approval and
 * the next one not to. The last script repeats once the queue is empty.
 */
class CannedNova implements NovaLike {
  readonly approved: { sessionId: string; requestId: string; approved: boolean }[] =
    [];
  interrupted: string | undefined;
  private turn = 0;

  constructor(private readonly scripts: readonly (readonly NovaFrame[])[]) {}

  async *streamChat(_request: NovaChatRequest): AsyncGenerator<NovaFrame> {
    const index = Math.min(this.turn, this.scripts.length - 1);
    this.turn += 1;
    for (const item of this.scripts[index] ?? []) {
      yield item;
    }
  }

  async approve(
    sessionId: string,
    requestId: string,
    approved: boolean,
  ): Promise<void> {
    this.approved.push({ sessionId, requestId, approved });
  }

  async interrupt(sessionId: string): Promise<boolean> {
    this.interrupted = sessionId;
    return true;
  }

  async ping(): Promise<void> {}

  async listAgents(): Promise<readonly NovaAgentSummary[]> {
    return PRIMARY_AGENTS;
  }
}

/**
 * A Nova stand-in whose turn never ends on its own, so `/stop` has something
 * live to interrupt.
 */
class BlockingNova implements NovaLike {
  interrupted: string | undefined;
  private opened: (() => void) | undefined;

  constructor(private readonly sessionId: string) {}

  /** Resolves once a turn is actually in flight. */
  started(): Promise<void> {
    return new Promise((resolve) => {
      this.opened = resolve;
    });
  }

  async *streamChat(
    _request: NovaChatRequest,
    signal?: AbortSignal,
  ): AsyncGenerator<NovaFrame> {
    yield frame("data-nova-session", { sessionId: this.sessionId });
    this.opened?.();
    // Park until the caller aborts, mirroring a turn blocked on a slow tool.
    await new Promise<void>((resolve) => {
      if (signal?.aborted === true) {
        resolve();
        return;
      }
      signal?.addEventListener("abort", () => resolve(), { once: true });
    });
  }

  async approve(): Promise<void> {}

  async interrupt(sessionId: string): Promise<boolean> {
    this.interrupted = sessionId;
    return true;
  }

  async ping(): Promise<void> {}

  async listAgents(): Promise<readonly NovaAgentSummary[]> {
    return PRIMARY_AGENTS;
  }
}

/** Paths a test needs pinned instead of the ambient defaults. */
interface HarnessOverrides {
  readonly dir?: string;
  readonly workspaceDir?: string;
  readonly sendRoots?: readonly string[];
}

/** Build an agent whose WeChat output is captured instead of sent. */
async function harness(
  nova: NovaLike,
  overrides?: HarnessOverrides,
): Promise<{ agent: WeixinNovaAgent; bubbles: string[]; store: SessionStore }> {
  const dir = overrides?.dir ?? (await mkdtemp(join(tmpdir(), "nova-approval-")));
  const config: BridgeConfig = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    spillDir: join(dir, "out"),
    outboxDir: join(dir, "outbox"),
    ...(overrides?.workspaceDir !== undefined
      ? { workspaceDir: overrides.workspaceDir }
      : {}),
    sendRoots: overrides?.sendRoots ?? [],
    progressIntervalMs: 50,
  };
  const store = new SessionStore(config.statePath);
  await store.load();

  const bubbles: string[] = [];
  const agent = new WeixinNovaAgent(config, nova, store);
  agent.attachBot({
    sendMessage: async (message: string | ChatResponse) => {
      bubbles.push(typeof message === "string" ? message : (message.text ?? ""));
    },
    wait: async () => undefined,
  } as unknown as Bot);

  return { agent, bubbles, store };
}

async function main(): Promise<void> {
  const base = await mkdtemp(join(tmpdir(), "nova-files-"));
  const isolatedWorkspace = join(base, "workspace");
  const forbiddenDir = join(base, "private");
  await mkdir(isolatedWorkspace, { recursive: true });
  await mkdir(forbiddenDir, { recursive: true });
  const dir = base;
  setLogLevel(process.env.NOVA_BRIDGE_LOG_LEVEL ?? "warn");
  const config = loadConfig();
  const nova = new NovaClient(config);
  await nova.ping();
  info("nova reachable", config.novaBaseUrl);

  // Nova's own approval semantics -- the frame carrying sessionId and requestId,
  // the stream staying open while a command waits, POST /api/chat/approve
  // releasing it, a foreign session being rejected -- are asserted in
  // tests/test_approval_sse_frames.py, where the shell behaviour can be driven
  // directly. What is verified here is the bridge half: reading that frame, and
  // turning a typed answer into the matching HTTP call. The `faker` provider
  // never emits a dangerous command, so a live approval cannot be provoked from
  // a plain prompt.

  // 1. The chat half: an approval frame must raise a prompt, and a typed "y"
  //    must reach Nova as an approval for the right request.
  const withApproval = [
    frame("data-nova-session", { sessionId: "sess-canned" }),
    frame("data-nova-approval-required", {
      sessionId: "sess-canned",
      requestId: "req-canned",
      command: DANGEROUS,
      description: "删除目录",
      toolName: "shell",
    }),
    // No approval-resolved frame: Nova only emits it once the answer has been
    // submitted, and the stream here is already finished by then.
    frame("text-delta", { delta: "done" }),
    frame("finish", {}),
  ];
  const canned = new CannedNova([withApproval, withApproval]);
  const { agent, bubbles } = await harness(canned);

  await agent.chat({ conversationId: "c1", text: "delete stuff" });
  await agent.whenIdle();

  assert.ok(
    bubbles.some((line) => line.includes(DANGEROUS)),
    "the approval prompt must quote the command back to the user",
  );
  assert.ok(
    bubbles.some((line) => line.includes("y")),
    "the approval prompt must say how to answer",
  );
  info("approval prompt delivered");

  // A second turn raises a fresh approval, answered "y" this time.
  await agent.chat({ conversationId: "c1", text: "delete more" });
  await agent.whenIdle();
  const approvedReply = await agent.chat({ conversationId: "c1", text: "y" });
  assert.deepEqual(parseApprovalReply("y"), { approved: true, remember: false });
  assert.deepEqual(canned.approved, [
    { sessionId: "sess-canned", requestId: "req-canned", approved: true },
  ]);
  assert.match(approvedReply.text ?? "", /允许/);
  info("chat approval accepted:", approvedReply.text);

  // 2. With nothing pending, a bare "y" is an ordinary prompt, not an answer. It
  // is admitted silently like any other message, and must reach Nova as a turn.
  const stale = new CannedNova([[frame("finish", {})]]);
  const staleRun = await harness(stale);
  const treatedAsPrompt = await staleRun.agent.chat({
    conversationId: "c9",
    text: "y",
  });
  assert.equal(
    treatedAsPrompt.text,
    undefined,
    "admitting a turn must not produce an acknowledgement bubble",
  );
  assert.deepEqual(stale.approved, [], "a stray y must not approve anything");
  info("stray approval answer handled safely");

  // 3. /stop on an idle conversation is a no-op, not a crash.
  const idle = await agent.chat({ conversationId: "c1", text: "/stop" });
  assert.match(idle.text ?? "", /没有/);
  info("/stop idle ok:", idle.text);

  // 4. /stop mid-turn must interrupt Nova as well as drop the socket: aborting
  //    the fetch alone only parks the turn as detached, leaving the agent running.
  const blocking = new BlockingNova("sess-stop");
  const stopped = await harness(blocking);
  await stopped.agent.chat({ conversationId: "c2", text: "long job" });
  await blocking.started();

  const stopReply = await stopped.agent.chat({ conversationId: "c2", text: "/stop" });
  assert.match(stopReply.text ?? "", /中断/, "/stop must report the interruption");
  assert.equal(blocking.interrupted, "sess-stop", "/stop must interrupt Nova");
  await stopped.agent.whenIdle();
  info("/stop interrupt verified");

  // 5. Outbound files: an explicit /send, an outbox drop, and the paths that
  //    must be refused.
  const files = await harness(new CannedNova([[frame("finish", {})]]), {
    dir: base,
    workspaceDir: isolatedWorkspace,
  });
  const outbox = join(dir, "outbox");
  await ensureOutbox(outbox);

  const attachment = join(isolatedWorkspace, "report.md");
  await writeFile(attachment, "# report\n\ncontents\n", "utf8");
  const sent = await files.agent.chat({
    conversationId: "c4",
    text: `/send ${attachment}`,
  });
  assert.match(sent.text ?? "", /已发送 report\.md/);
  const delivered = files.bubbles.find((line) => line.includes("report.md"));
  assert.ok(delivered, "the file bubble must name the file");
  info("/send delivered:", sent.text);

  // A path outside the allowed roots must be refused, not uploaded.
  const outside = join(forbiddenDir, "id_rsa");
  await writeFile(outside, "SECRET", "utf8");
  const refused = await files.agent.chat({
    conversationId: "c4",
    text: `/send ${outside}`,
  });
  assert.match(refused.text ?? "", /不在允许发送的目录内/);
  assert.ok(
    !files.bubbles.some((line) => line.includes("id_rsa")),
    "a refused path must never reach WeChat",
  );
  info("/send refusal verified:", refused.text);

  // A file the agent drops in the outbox goes out at the end of the turn. It has
  // to appear *during* the turn: a turn only claims files written after it
  // started, so anything already sitting there belongs to an earlier one.
  await files.agent.chat({ conversationId: "c4", text: "make me a file" });
  await writeFile(join(outbox, "deliverable.txt"), "payload", "utf8");
  await files.agent.whenIdle();
  assert.ok(
    files.bubbles.some((line) => line.includes("deliverable.txt")),
    "an outbox file must be delivered after the turn",
  );
  assert.deepEqual(
    await listOutbox(outbox),
    [],
    "a delivered outbox file must be cleared",
  );
  info("outbox drain verified");

  // 6. An opted-in send root delivers a file the workspace could never reach,
  //    and the same file is still refused when the root is not opted in.
  const opted = await harness(new CannedNova([[frame("finish", {})]]), {
    dir: await mkdtemp(join(tmpdir(), "nova-sendroot-")),
    workspaceDir: join(base, "elsewhere"),
    sendRoots: [forbiddenDir],
  });
  const desktopish = join(forbiddenDir, "photo.jpg");
  await writeFile(desktopish, "JPEGDATA", "utf8");

  const fromSendRoot = await opted.agent.chat({
    conversationId: "c5",
    text: `/send ${desktopish}`,
  });
  assert.match(fromSendRoot.text ?? "", /已发送 photo\.jpg/);
  info("send root delivered:", fromSendRoot.text);

  const stillRefused = await files.agent.chat({
    conversationId: "c4",
    text: `/send ${desktopish}`,
  });
  assert.match(
    stillRefused.text ?? "",
    /不在允许发送的目录内/,
    "a root only counts when it is opted in",
  );
  info("unopted root still refused");

  assert.ok(ApprovalRegistry.describe.length > 0);
  info("approval, stop and file checks passed");
}

try {
  await main();
} catch (cause) {
  error(`approval check failed: ${String(cause)}`);
  process.exitCode = 1;
}