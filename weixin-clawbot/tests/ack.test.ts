/**
 * The acknowledgement a message gets, and the silence that replaces it.
 *
 * The SDK sends nothing when `chat()` returns no text, so an unconditional
 * "已收到" would put a boilerplate bubble in front of every real answer. These
 * tests pin that silence, and that a turn which says nothing still gets told it
 * is alive.
 */

import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";
import { WeixinNovaAgent } from "../src/agent.js";
import { loadConfig } from "../src/config.js";
import type {
  NovaAgentSummary,
  NovaChatRequest,
  NovaFrame,
  NovaLike,
} from "../src/nova.js";
import { PRIMARY_AGENTS } from "./fixtures.js";
import { SessionStore } from "../src/sessions.js";
import type { ChatResponse } from "weixin-agent-sdk";

/** One AI-SDK frame as it arrives on the wire. */
function frame(type: string, extra: Record<string, unknown> = {}): NovaFrame {
  return { type, sequence: undefined, payload: { type, ...extra } };
}

/** A Nova stand-in whose turn can be held open or finished immediately. */
class ControlledNova implements NovaLike {
  private release: (() => void) | null = null;

  constructor(private readonly silent: boolean) {}

  /** Let a held turn finish. */
  finish(): void {
    const release = this.release;
    this.release = null;
    release?.();
  }

  async *streamChat(_request: NovaChatRequest): AsyncGenerator<NovaFrame> {
    yield frame("data-nova-session", { data: { sessionId: "s1" } });
    yield frame("start");
    yield frame("start-step");
    if (this.silent) {
      await new Promise<void>((resolve) => {
        this.release = resolve;
      });
      yield frame("finish-step");
    } else {
      yield frame("text-start", { id: "t1" });
      yield frame("text-delta", { id: "t1", delta: "答案在这里。" });
      yield frame("text-end", { id: "t1" });
      yield frame("finish-step");
    }
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

/** Build an agent whose WeChat output is captured instead of sent. */
async function agentFor(
  nova: NovaLike,
  overrides: { stillWorkingMs?: number } = {},
): Promise<{ agent: WeixinNovaAgent; bubbles: string[] }> {
  const dir = await mkdtemp(join(tmpdir(), "nova-ack-"));
  const config = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    spillDir: join(dir, "out"),
    outboxDir: join(dir, "outbox"),
    progressIntervalMs: 100_000,
    stillWorkingMs: overrides.stillWorkingMs ?? 60,
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
  } as unknown as Parameters<typeof agent.attachBot>[0]);

  return { agent, bubbles };
}

describe("acknowledgement", () => {
  it("returns no text, so the SDK sends nothing", async () => {
    const { agent, bubbles } = await agentFor(new ControlledNova(false));
    const reply = await agent.chat({ conversationId: "c", text: "hi" });
    await agent.whenIdle();

    assert.equal(reply.text, undefined, "an empty reply keeps the SDK silent");
    assert.ok(!bubbles.some((line) => line.includes("已收到")), "no ack bubble");
    assert.equal(bubbles.at(-1), "答案在这里。", "only the real answer arrives");
  });

  it("tells a silent turn it is alive instead of staying mute", async () => {
    const nova = new ControlledNova(true);
    const { agent, bubbles } = await agentFor(nova, { stillWorkingMs: 60 });

    await agent.chat({ conversationId: "c", text: "long job" });
    await new Promise((resolve) => setTimeout(resolve, 250));

    assert.ok(
      bubbles.some((line) => /仍在处理/.test(line)),
      "a slow turn must not look dead",
    );
    assert.ok(
      bubbles.every((line) => !line.includes("已收到")),
      "still no acknowledgement boilerplate",
    );

    nova.finish();
    await agent.whenIdle();
  });

  it("reports the dropped attachment immediately rather than in an ack", async () => {
    const { agent, bubbles } = await agentFor(new ControlledNova(false));
    await agent.chat({
      conversationId: "c",
      text: "看看这个",
      media: {
        type: "file",
        filePath: "/tmp/report.pdf",
        mimeType: "application/pdf",
      },
    });
    await agent.whenIdle();

    assert.ok(
      bubbles.some((line) => /file 类型 Nova 暂不支持/.test(line)),
      "an ignored attachment must be said out loud",
    );
    assert.equal(bubbles.at(-1), "答案在这里。");
  });

  it("says nothing extra when the message carries a usable image", async () => {
    const { agent, bubbles } = await agentFor(new ControlledNova(false));
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    );
    const { mkdtemp: mk, writeFile } = await import("node:fs/promises");
    const dir = await mk(join(tmpdir(), "nova-ack-img-"));
    const path = join(dir, "dot.png");
    await writeFile(path, png);

    await agent.chat({
      conversationId: "c",
      text: "这是什么",
      media: { type: "image", filePath: path, mimeType: "image/png" },
    });
    await agent.whenIdle();

    assert.ok(
      bubbles.every((line) => !/暂不支持/.test(line)),
      "a usable attachment must not be reported as dropped",
    );
    assert.equal(bubbles.at(-1), "答案在这里。");
  });
});