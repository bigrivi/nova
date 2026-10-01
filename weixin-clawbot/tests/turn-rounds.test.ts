/**
 * Which assistant message reaches the chat as the reply.
 *
 * Nova's agent loop runs several LLM rounds per turn, and a model often says
 * something before calling a tool. Concatenating every `text-delta` splices
 * those intermediate remarks into the answer, so the bridge resets on
 * `start-step` and keeps only the final round.
 *
 * DONE's content is not usable here: `AISDKStreamAdapter` emits it only when no
 * text was streamed at all, so on the normal path it never reaches the wire.
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

/** Builds one AI-SDK frame as it arrives on the wire. */
function frame(type: string, extra: Record<string, unknown> = {}): NovaFrame {
  return { type, sequence: undefined, payload: { type, ...extra } };
}

/** Replays a fixed frame list, so multi-round turns are reproducible. */
class ScriptedNova implements NovaLike {
  constructor(private readonly frames: readonly NovaFrame[]) {}

  async *streamChat(_request: NovaChatRequest): AsyncGenerator<NovaFrame> {
    for (const item of this.frames) {
      yield item;
    }
  }

  async approve(): Promise<void> {}
  async interrupt(): Promise<boolean> {
    return true;
  }
  async ping(): Promise<void> {}

  async listAgents(): Promise<readonly NovaAgentSummary[]> {
    return PRIMARY_AGENTS;
  }
}

/** An agent whose WeChat output is captured instead of sent. */
async function agentFor(frames: readonly NovaFrame[]): Promise<{
  agent: WeixinNovaAgent;
  bubbles: string[];
}> {
  const dir = await mkdtemp(join(tmpdir(), "nova-rounds-"));
  const config = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    spillDir: join(dir, "out"),
    outboxDir: join(dir, "outbox"),
    maxTextChars: 100_000,
    progressIntervalMs: 100_000,
  };
  const store = new SessionStore(config.statePath);
  await store.load();

  const bubbles: string[] = [];
  const agent = new WeixinNovaAgent(config, new ScriptedNova(frames), store);
  agent.attachBot({
    sendMessage: async (message: string | ChatResponse) => {
      bubbles.push(typeof message === "string" ? message : (message.text ?? ""));
    },
    wait: async () => undefined,
  } as unknown as Parameters<typeof agent.attachBot>[0]);

  return { agent, bubbles };
}

describe("multi-round turns", () => {
  it("keeps only the last round when the model speaks before a tool call", async () => {
    const { agent, bubbles } = await agentFor([
      frame("data-nova-session", { data: { sessionId: "s1" } }),
      frame("start"),
      frame("start-step"),
      frame("text-start", { id: "t1" }),
      frame("text-delta", { id: "t1", delta: "让我看看这个目录。" }),
      frame("text-end", { id: "t1" }),
      frame("finish-step"),
      frame("tool-input-available", {
        toolCallId: "c1",
        toolName: "shell",
        input: { command: "ls -la" },
      }),
      frame("tool-output-available", { toolCallId: "c1", output: { content: "ok" } }),
      frame("start-step"),
      frame("text-start", { id: "t2" }),
      frame("text-delta", { id: "t2", delta: "目录里有 3 个文件。" }),
      frame("text-end", { id: "t2" }),
      frame("finish-step"),
      frame("finish"),
      frame("[DONE]"),
    ]);

    await agent.chat({ conversationId: "c", text: "看看目录" });
    await agent.whenIdle();

    const final = bubbles.at(-1) ?? "";
    assert.equal(final, "目录里有 3 个文件。", "the answer must be the last round only");
    assert.ok(
      !final.includes("让我看看"),
      "the pre-tool remark must not be spliced into the reply",
    );
  });

  it("still delivers a single-round answer unchanged", async () => {
    const { agent, bubbles } = await agentFor([
      frame("data-nova-session", { data: { sessionId: "s1" } }),
      frame("start"),
      frame("start-step"),
      frame("text-start", { id: "t1" }),
      frame("text-delta", { id: "t1", delta: "直接回答。" }),
      frame("text-end", { id: "t1" }),
      frame("finish-step"),
      frame("finish"),
      frame("[DONE]"),
    ]);

    await agent.chat({ conversationId: "c", text: "hi" });
    await agent.whenIdle();
    assert.equal(bubbles.at(-1), "直接回答。");
  });

  it("reports no content when the last round produced no text", async () => {
    const { agent, bubbles } = await agentFor([
      frame("data-nova-session", { data: { sessionId: "s1" } }),
      frame("start"),
      frame("start-step"),
      frame("text-delta", { id: "t1", delta: "先说一句。" }),
      frame("finish-step"),
      frame("tool-input-available", {
        toolCallId: "c1",
        toolName: "shell",
        input: { command: "true" },
      }),
      frame("start-step"),
      frame("finish-step"),
      frame("finish"),
      frame("[DONE]"),
    ]);

    await agent.chat({ conversationId: "c", text: "go" });
    await agent.whenIdle();
    assert.match(bubbles.at(-1) ?? "", /没有返回内容/);
  });

  it("keeps the pre-tool remark as progress, not as the reply", async () => {
    // The remark is still shown live, just not as the answer.
    const { agent, bubbles } = await agentFor([
      frame("data-nova-session", { data: { sessionId: "s1" } }),
      frame("start"),
      frame("start-step"),
      frame("text-delta", { id: "t1", delta: "稍等。" }),
      frame("finish-step"),
      frame("tool-input-available", {
        toolCallId: "c1",
        toolName: "shell",
        input: { command: "true" },
      }),
      frame("start-step"),
      frame("text-delta", { id: "t2", delta: "好了。" }),
      frame("finish-step"),
      frame("finish"),
      frame("[DONE]"),
    ]);

    await agent.chat({ conversationId: "c", text: "go" });
    await agent.whenIdle();

    assert.equal(bubbles.at(-1), "好了。");
    assert.ok(
      bubbles.some((line) => line.includes("shell")),
      "the tool call is still reported",
    );
  });
});