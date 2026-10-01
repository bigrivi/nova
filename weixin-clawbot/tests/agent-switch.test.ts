/**
 * `/agent` switching: one ClawBot, several Nova agents.
 *
 * WeChat allows a single ClawBot per account, so the agent cannot be inferred
 * from which bot received the message -- the user picks it in-band. That makes
 * isolation load-bearing rather than tidiness: one WeChat user reaches every
 * agent under the same `conversationId`, so if the namespace did not follow the
 * selection, two personas would share one Nova session and read each other's
 * history.
 */

import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import type { Bot, ChatResponse } from "weixin-agent-sdk";
import { WeixinNovaAgent } from "../src/agent.js";
import { loadConfig, type BridgeConfig } from "../src/config.js";
import { CurrentAgentStore } from "../src/current-agent.js";
import type {
  NovaAgentSummary,
  NovaChatRequest,
  NovaFrame,
  NovaLike,
} from "../src/nova.js";
import { SessionStore } from "../src/sessions.js";
import { PRIMARY_AGENTS, SUBAGENT_KEY } from "./fixtures.js";

/** Session ids are unique across instances, as Nova's uuid4 ones are. */
let mintedSessions = 0;

/** One AI-SDK frame as it arrives on the wire. */
function frame(type: string, extra: Record<string, unknown> = {}): NovaFrame {
  return { type, sequence: undefined, payload: { type, ...extra } };
}

interface ScriptedOptions {
  /** Hold every turn until `release()` is called. */
  readonly hold?: boolean;
  /** Emit an approval prompt and then wait, as a gated command does. */
  readonly approval?: boolean;
}

class ScriptedNova implements NovaLike {
  /** The agent key each admitted turn was addressed to, in order. */
  readonly agentsAsked: string[] = [];
  /** Run mid-turn, where the real agent would drop a deliverable. */
  onTurn: ((request: NovaChatRequest) => Promise<void>) | null = null;
  private release: (() => void) | null = null;
  private preReleased = false;

  constructor(private readonly options: ScriptedOptions = {}) {}

  /** Let a held turn finish, whichever order the test calls this in. */
  release_(): void {
    if (this.release !== null) {
      this.release();
      this.release = null;
      return;
    }
    this.preReleased = true;
  }

  async *streamChat(request: NovaChatRequest): AsyncGenerator<NovaFrame> {
    this.agentsAsked.push(request.agentKey ?? "<none>");
    mintedSessions += 1;
    const sessionId = request.sessionId ?? `sess-${mintedSessions}`;
    yield frame("data-nova-session", { data: { sessionId } });
    yield frame("start");
    yield frame("start-step");
    if (this.options.approval === true) {
      yield frame("data-nova-approval-required", {
        data: {
          sessionId,
          requestId: "req-1",
          command: "rm -rf build",
          description: "delete the build directory",
        },
      });
      await new Promise<void>((resolve) => {
        this.release = resolve;
      });
    }
    await this.onTurn?.(request);
    if (this.options.hold === true && !this.preReleased) {
      await new Promise<void>((resolve) => {
        this.release = resolve;
      });
    }
    this.preReleased = false;
    yield frame("text-start", { id: "t" });
    yield frame("text-delta", { id: "t", delta: "好了。" });
    yield frame("text-end", { id: "t" });
    yield frame("finish-step");
    yield frame("finish");
    yield frame("[DONE]");
  }

  async approve(): Promise<void> {
    this.release_();
  }

  async interrupt(): Promise<boolean> {
    this.release_();
    return true;
  }

  async ping(): Promise<void> {}

  async listAgents(): Promise<readonly NovaAgentSummary[]> {
    return PRIMARY_AGENTS;
  }
}

interface Harness {
  readonly agent: WeixinNovaAgent;
  readonly current: CurrentAgentStore;
  readonly sessions: SessionStore;
  readonly nova: ScriptedNova;
  readonly outbox: string;
  readonly bubbles: string[];
  /** Admit a message and collect everything that turn pushed. */
  turn(sender: string, text: string): Promise<readonly string[]>;
  /** Admit a message and return the inline reply (slash commands). */
  say(sender: string, text: string): Promise<string>;
}

async function harness(
  nova: ScriptedNova,
  overrides: Partial<BridgeConfig> = {},
): Promise<Harness> {
  const dir = await mkdtemp(join(tmpdir(), "nova-switch-"));
  const outbox = join(dir, "outbox");
  await mkdir(outbox, { recursive: true });
  const config: BridgeConfig = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    currentAgentPath: join(dir, "current.json"),
    spillDir: join(dir, "out"),
    outboxDir: outbox,
    progressIntervalMs: 100_000,
    stillWorkingMs: 100_000,
    ...overrides,
  };

  const sessions = new SessionStore(join(dir, "sessions.json"));
  await sessions.load();

  const current = new CurrentAgentStore(config.currentAgentPath);
  await current.load();
  const bubbles: string[] = [];
  const agent = new WeixinNovaAgent(config, nova, sessions, null, undefined, {
    currentAgents: current,
  });
  agent.attachBot({
    sendMessage: async (message: string | ChatResponse) => {
      bubbles.push(
        typeof message === "string" ? message : (message.text ?? ""),
      );
    },
    wait: async () => undefined,
  } as unknown as Bot);

  return {
    agent,
    current,
    nova,
    outbox,
    bubbles,
    sessions,
    say: async (sender, text) => {
      const reply = await agent.chat({ conversationId: sender, text });
      return reply.text ?? "";
    },
    turn: async (sender, text) => {
      bubbles.length = 0;
      await agent.chat({ conversationId: sender, text });
      await agent.whenIdle();
      return bubbles;
    },
  };
}

const SENDER = "ilink-user-1";

describe("/agent", () => {
  it("lists the primary agents by index and marks the current one", async () => {
    const h = await harness(new ScriptedNova());

    const listed = await h.say(SENDER, "/agent");

    assert.match(listed, /main/);
    assert.match(listed, /writing-coach/);
    assert.match(listed, /main .*<- 当前/s);
    assert.match(listed, /^1\. /m, "entries are numbered from one");
  });

  it("switches by index", async () => {
    const h = await harness(new ScriptedNova());
    // Sorted by key: main(1), writing-coach(2).
    assert.match(await h.say(SENDER, "/agent"), /^2\. writing-coach/m);

    assert.match(await h.say(SENDER, "/agent 2"), /已切换到 writing-coach/);
    assert.match(await h.say(SENDER, "/status"), /Agent writing-coach/);
  });

  it("still switches by key, so the long form keeps working", async () => {
    const h = await harness(new ScriptedNova());

    assert.match(
      await h.say(SENDER, "/agent writing-coach"),
      /已切换到 writing-coach/,
    );
  });

  it("echoes the key after an index switch, so a miscount is visible", async () => {
    const h = await harness(new ScriptedNova());

    // The whole point of numbering: if 2 turns out to be the wrong one, the
    // reply says which agent was actually reached before anything is sent to it.
    assert.match(await h.say(SENDER, "/agent 1"), /已经在跟 main/);
  });

  it("orders the list by key, so a rename cannot shift the indices", async () => {
    const h = await harness(new ScriptedNova());

    const listed = await h.say(SENDER, "/agent");
    const keys = [...listed.matchAll(/^\d+\. (\S+)/gm)].map((m) => m[1]);

    assert.deepEqual(keys, ["main", "writing-coach"], "sorted by key, not by name");
  });

  it("creates the switched agent's outbox so it can be written to", async () => {
    const h = await harness(new ScriptedNova());
    const coachOutbox = join(h.outbox, "writing-coach");

    await h.say(SENDER, "/agent 2");

    assert.ok(
      existsSync(coachOutbox),
      "an agent becomes able to deliver files the moment it is selected",
    );
  });

  it("rejects an index past the end of the list", async () => {
    const h = await harness(new ScriptedNova());

    const reply = await h.say(SENDER, "/agent 99");

    assert.match(reply, /没有第 99 个/);
    assert.match(reply, /共 2 个/);
  });

  it("rejects index zero rather than reading it as the last entry", async () => {
    // `ordered[Number("0") - 1]` is `ordered[-1]`, which is undefined here -- but
    // a future refactor to modulo arithmetic would make this silently wrap.
    const h = await harness(new ScriptedNova());

    assert.match(await h.say(SENDER, "/agent 0"), /没有第 0 个/);
  });

  it("addresses the turn to the agent the user selected", async () => {
    const h = await harness(new ScriptedNova());

    await h.turn(SENDER, "帮我写点东西");
    assert.match(await h.say(SENDER, "/agent writing-coach"), /已切换到/);
    await h.turn(SENDER, "帮我润色");

    assert.deepEqual(h.nova.agentsAsked, ["main", "writing-coach"]);
  });

  it("gives each agent its own session, and resumes it on the way back", async () => {
    const h = await harness(new ScriptedNova());

    await h.turn(SENDER, "第一次");
    const firstMain = (await h.say(SENDER, "/status")).match(/会话 (\S+)/)?.[1];

    await h.say(SENDER, "/agent writing-coach");
    await h.turn(SENDER, "教练的第一句");
    const coachSession = (
      await h.say(SENDER, "/status")
    ).match(/会话 (\S+)/)?.[1];

    await h.say(SENDER, "/agent main");
    const backOnMain = (await h.say(SENDER, "/status")).match(/会话 (\S+)/)?.[1];

    assert.ok(firstMain, "main must have a session");
    assert.ok(coachSession, "the switched agent must have its own session");
    assert.notEqual(
      firstMain,
      coachSession,
      "two personas must not share one Nova session",
    );
    assert.equal(backOnMain, firstMain, "switching back must resume the session");
  });

  it("delivers only the running agent's outbox files", async () => {
    const nova = new ScriptedNova();
    const h = await harness(nova);
    const coachOutbox = join(h.outbox, "writing-coach");
    nova.onTurn = async (request) => {
      if (request.agentKey !== "writing-coach") {
        return;
      }
      await mkdir(coachOutbox, { recursive: true });
      await writeFile(join(coachOutbox, "coach.md"), "教练的稿子", "utf8");
    };

    // main's turn runs first and must not reach into the coach's outbox -- nor
    // complain about the coach's folder, which is structure the bridge made.
    await h.turn(SENDER, "我只要文字");
    assert.deepEqual(
      h.bubbles.filter((bubble) => !bubble.startsWith("会话 ")),
      ["好了。"],
      `main must neither deliver nor mention the coach's outbox, saw ${JSON.stringify(h.bubbles)}`,
    );

    await h.say(SENDER, "/agent writing-coach");
    h.bubbles.length = 0;
    await h.turn(SENDER, "交付文件");

    assert.ok(
      h.bubbles.some((bubble) => bubble.includes("coach.md")),
      `expected the coach's file to be delivered, saw ${JSON.stringify(h.bubbles)}`,
    );
  });

  it("refuses a subagent, which is never switchable to", async () => {
    // Nova applies an agent's posture only to subagents, so a read_only one
    // reached over the primary chat path would hold the full toolset.
    const h = await harness(new ScriptedNova());

    const reply = await h.say(SENDER, `/agent ${SUBAGENT_KEY}`);

    assert.match(reply, /没有名为 researcher/);
    assert.match(reply, /序号/);
  });

  it("refuses an unknown agent and names the real ones", async () => {
    const h = await harness(new ScriptedNova());

    const reply = await h.say(SENDER, "/agent nope");

    assert.match(reply, /没有名为 nope/);
  });

  it("cannot be talked into a path outside the state directory", async () => {
    // A key becomes a path segment and a turn-gate key, so a traversal attempt
    // must resolve to nothing. It cannot match, because the only accepted target
    // is a key Nova itself reported -- the input is never used as a path.
    const h = await harness(new ScriptedNova());

    for (const attempt of ["../../etc", "..%2f..%2fetc", "/etc/passwd"]) {
      const reply = await h.say(SENDER, `/agent ${attempt}`);
      assert.match(reply, /没有名为/, `"${attempt}" must not resolve`);
    }
    assert.equal(
      h.current.get(SENDER),
      undefined,
      "no traversal attempt may change the selection",
    );
  });

  it("says so when asked to switch to the agent already in use", async () => {
    const h = await harness(new ScriptedNova());

    assert.match(await h.say(SENDER, "/agent main"), /已经在跟 main/);
  });

  it("refuses to switch while a turn is running", async () => {
    const nova = new ScriptedNova({ hold: true });
    const h = await harness(nova);
    void h.turn(SENDER, "长任务");
    // Let the turn reach its wait before asking to switch underneath it.
    await new Promise((resolve) => {
      setTimeout(resolve, 20);
    });

    const reply = await h.say(SENDER, "/agent writing-coach");

    assert.match(reply, /还有一个任务在跑/);
    nova.release_();
    await h.agent.whenIdle();
  });

  it("refuses to switch while an approval is unanswered", async () => {
    const nova = new ScriptedNova({ approval: true });
    const h = await harness(nova);
    void h.turn(SENDER, "删掉 build");
    await new Promise((resolve) => {
      setTimeout(resolve, 20);
    });

    const reply = await h.say(SENDER, "/agent writing-coach");

    assert.match(reply, /审批/);
    await h.say(SENDER, "n");
    await h.agent.whenIdle();
  });

  it("remembers the selection across a restart", async () => {
    const dir = await mkdtemp(join(tmpdir(), "nova-switch-"));
    const path = join(dir, "current.json");

    const first = new CurrentAgentStore(path);
    await first.load();
    await first.set(SENDER, "writing-coach");

    const second = new CurrentAgentStore(path);
    await second.load();

    assert.equal(second.get(SENDER), "writing-coach");
  });

  it("honours a pinned agent by refusing to switch at all", async () => {
    const h = await harness(new ScriptedNova(), { onlyAgent: "main" });

    const reply = await h.say(SENDER, "/agent writing-coach");

    assert.match(reply, /固定在 main/);
    assert.match(await h.say(SENDER, "/status"), /Agent main/);
  });

  it("drives a pinned agent even after something recorded a switch", async () => {
    const h = await harness(new ScriptedNova(), { onlyAgent: "main" });
    await h.current.set(SENDER, "writing-coach");

    await h.turn(SENDER, "你好");

    assert.deepEqual(h.nova.agentsAsked, ["main"]);
  });
});
