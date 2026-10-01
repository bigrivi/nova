/**
 * Multiple senders on one bridge.
 *
 * The outbox is a single directory an agent writes into without knowing which
 * conversation it is serving, so concurrent turns would hand one sender another
 * sender's files. One turn at a time makes attribution unambiguous. These tests
 * pin that, plus the sender allowlist that keeps a stranger from reaching the
 * agent at all.
 */

import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import type { Bot, ChatResponse } from "weixin-agent-sdk";
import { WeixinNovaAgent } from "../src/agent.js";
import { loadConfig, type BridgeConfig } from "../src/config.js";
import { isExpiredSession, REBIND_HINT } from "../src/sdk-log.js";
import type {
  NovaAgentSummary,
  NovaChatRequest,
  NovaFrame,
  NovaLike,
} from "../src/nova.js";
import { PRIMARY_AGENTS } from "./fixtures.js";
import { SessionStore } from "../src/sessions.js";

/** One AI-SDK frame as it arrives on the wire. */
function frame(type: string, extra: Record<string, unknown> = {}): NovaFrame {
  return { type, sequence: undefined, payload: { type, ...extra } };
}

/**
 * Answers immediately, except for the first `holdCount` turns which wait to be
 * released. "The first turn is slow, later ones are quick" is what the overlap
 * tests need, and a plain boolean would block every later turn too.
 */
/** Session ids are unique across instances, as Nova's uuid4 ones are. */
let mintedSessions = 0;

class ScriptedNova implements NovaLike {
  private release: (() => void) | null = null;
  private preReleased = false;
  private seen = 0;

  constructor(private readonly options: { readonly holdCount?: number } = {}) {}

  /**
   * Let a held turn finish.
   *
   * Records the release when it arrives before the turn reaches its wait, so a
   * test cannot hang by calling this in the wrong order.
   */
  finish(): void {
    if (this.release !== null) {
      this.release();
      this.release = null;
      return;
    }
    this.preReleased = true;
  }

  async *streamChat(request: NovaChatRequest): AsyncGenerator<NovaFrame> {
    this.seen += 1;
    // Mirror Nova: a supplied session id is reused, otherwise one is minted, so
    // two conversations do not land in the same session.
    mintedSessions += 1;
    const sessionId = request.sessionId ?? `sess-${mintedSessions}`;
    yield frame("data-nova-session", { data: { sessionId } });
    yield frame("start");
    yield frame("start-step");
    if (this.seen <= (this.options.holdCount ?? 0) && !this.preReleased) {
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

  async approve(): Promise<void> {}
  async interrupt(): Promise<boolean> {
    this.finish();
    return true;
  }
  async ping(): Promise<void> {}

  async listAgents(): Promise<readonly NovaAgentSummary[]> {
    return PRIMARY_AGENTS;
  }
}

/** A bridge whose WeChat output is captured instead of sent. */
interface Harness {
  agent: WeixinNovaAgent;
  store: SessionStore;
  outbox: string;
  /** Everything pushed since the last `turn`, flattened. */
  bubbles: string[];
  /** Admit a message and collect everything that turn pushed. */
  turn(sender: string, text: string): Promise<readonly string[]>;
}

/** A `turn` body so the sent message is awaited before inspecting output. */
function admit(h: Harness, sender: string, text: string): Promise<ChatResponse> {
  h.bubbles.length = 0;
  return h.agent.chat({ conversationId: sender, text });
}

async function harness(
  nova: NovaLike,
  overrides: Partial<BridgeConfig> = {},
): Promise<Harness> {
  const dir = await mkdtemp(join(tmpdir(), "nova-senders-"));
  const outbox = join(dir, "outbox");
  await mkdir(outbox, { recursive: true });
  const config: BridgeConfig = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    spillDir: join(dir, "out"),
    outboxDir: outbox,
    progressIntervalMs: 100_000,
    stillWorkingMs: 100_000,
    ...overrides,
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

  return {
    agent,
    store,
    outbox,
    bubbles,
    turn: async (sender, text) => {
      await admit({ agent, store, outbox, bubbles, turn: async () => [] }, sender, text);
      await agent.whenIdle();
      return bubbles;
    },
  };
}

describe("SDK log routing", () => {
  it("recognises an expired session in the SDK's wording", () => {
    assert.equal(
      isExpiredSession(
        "session expired (errcode -14), pausing for 60 min. Please run `npx weixin-acp login` to re-login.",
      ),
      true,
    );
    assert.equal(isExpiredSession("getUpdates failed: ret=0 errcode=-14"), true);
    assert.equal(isExpiredSession("inbound: from=abc types=text"), false);
    assert.equal(isExpiredSession("monitor started"), false);
  });

  it("points at this bridge's own rebind command, not the SDK's", () => {
    // The SDK suggests `npx weixin-acp login`, which belongs to the ACP wrapper
    // and does not exist here. Following it would waste an hour of cooldown.
    assert.match(REBIND_HINT, /npm run login/);
    assert.ok(!REBIND_HINT.includes("weixin-acp"));
  });
});

describe("multiple senders", () => {
  it("refuses a second sender while a turn is running", async () => {
    const nova = new ScriptedNova({ holdCount: 1 });
    const h = await harness(nova);

    const alice = admit(h, "alice", "长任务");
    await new Promise((resolve) => setTimeout(resolve, 60));

    const bobReply = await h.agent.chat({ conversationId: "bob", text: "插队" });
    assert.match(bobReply.text ?? "", /另一个任务在跑/, "bob must be turned away");

    nova.finish();
    await alice;
    await h.agent.whenIdle();

    const after = await h.agent.chat({ conversationId: "bob", text: "现在可以了" });
    assert.equal(after.text, undefined, "bob gets in once the turn is free");
    nova.finish();
    await h.agent.whenIdle();
  });

  it("keeps a file produced by one turn out of another sender's chat", async () => {
    // The regression: a shared outbox plus overlapping turns let bob's drain pick
    // up alice's file and delete it, so alice never received it at all. The
    // overlap has to be real, so alice is still mid-turn when bob arrives.
    const nova = new ScriptedNova({ holdCount: 1 });
    const h = await harness(nova);

    const alice = admit(h, "alice", "生成文件");
    await new Promise((resolve) => setTimeout(resolve, 60));
    await writeFile(join(h.outbox, "alice-report.pdf"), "ALICE", "utf8");

    // Bob tries to slip in while alice's file is undrained.
    h.bubbles.length = 0;
    const bobDuringOverlap = await h.agent.chat({
      conversationId: "bob",
      text: "插队",
    });

    nova.finish();
    await alice;
    await h.agent.whenIdle();

    const aliceGot = h.bubbles.some((line) => line.includes("alice-report.pdf"));
    assert.ok(
      aliceGot,
      "alice must receive her own file; bob draining it first is the bug",
    );
    assert.match(
      bobDuringOverlap.text ?? "",
      /另一个任务在跑/,
      "bob's overlapping request must be refused, not run",
    );
    assert.deepEqual(await readdir(h.outbox), [], "the delivered file is cleared");
  });

  it("never hands a previous sender's leftover file to the next one", async () => {
    const nova = new ScriptedNova({ holdCount: 1 });
    const h = await harness(nova);

    // A turn that is interrupted before its drain leaves the file behind.
    const alice = admit(h, "alice", "生成文件");
    await new Promise((resolve) => setTimeout(resolve, 60));
    await writeFile(join(h.outbox, "orphan.pdf"), "ORPHAN", "utf8");
    await h.agent.chat({ conversationId: "alice", text: "/stop" });
    nova.finish();
    await alice;
    await h.agent.whenIdle();

    await h.turn("bob", "我的问题");
    assert.ok(
      !h.bubbles.some((line) => line.includes("orphan.pdf")),
      "a file left by another sender must not be picked up",
    );
  });

  it("gives each sender its own Nova session, namespaced by agent", async () => {
    const h = await harness(new ScriptedNova());
    await h.turn("alice", "第一个问题");
    await h.turn("bob", "第二个问题");

    const aliceSession = h.store.sessionFor("main/alice");
    const bobSession = h.store.sessionFor("main/bob");
    assert.ok(aliceSession && bobSession, "both senders get a session");
    assert.notEqual(aliceSession, bobSession, "sessions are not shared");

    // The owner's review surface: both conversations are bound under their own
    // namespaced keys, so both appear in Nova's session list.
    assert.equal(h.store.sessionFor("alice"), undefined, "the bare key must not resolve");
    assert.equal(h.store.sessionFor("bob"), undefined, "the bare key must not resolve");
  });

  it("reports which sender is talking in /status", async () => {
    const h = await harness(new ScriptedNova());
    const status = await h.agent.chat({
      conversationId: "alice-ilink-id",
      text: "/status",
    });
    assert.match(status.text ?? "", /发送者 alice-ilink-id/);
  });
});

describe("NOVA_ALLOWED_SENDERS", () => {
  it("refuses a sender outside the list without reaching Nova", async () => {
    const nova = new ScriptedNova();
    const h = await harness(nova, { allowedSenders: ["alice"] });

    const rejected = await h.agent.chat({
      conversationId: "mallory",
      text: "rm -rf ~",
    });
    assert.match(rejected.text ?? "", /私人的/);

    await h.turn("alice", "正常问题");
    assert.ok(h.bubbles.length > 0, "an allowed sender reaches the agent");
  });

  it("still answers /help and /status for an unlisted sender", async () => {
    const h = await harness(new ScriptedNova(), { allowedSenders: ["alice"] });
    const help = await h.agent.chat({
      conversationId: "mallory",
      text: "/help",
    });
    assert.match(help.text ?? "", /\/send/, "commands stay available");
  });

  it("admits everyone when the list is empty", async () => {
    const h = await harness(new ScriptedNova(), { allowedSenders: [] });
    const reply = await h.agent.chat({ conversationId: "anyone", text: "hi" });
    assert.equal(reply.text, undefined, "empty allowlist keeps the open default");
    await h.agent.whenIdle();
  });
});