/**
 * The model's narration reaches the user before the tool line it explains.
 *
 * Nova emits `text-delta` before `tool-input-available` often enough to matter --
 * "我搜一下。" then the search. The bridge used to accumulate that text into the
 * turn's answer and wipe it on the next `start-step`, so it was never sent at
 * all and the tool calls arrived unexplained.
 *
 * The frames below are the ones captured from a real `main` turn.
 */

import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
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
import { PRIMARY_AGENTS } from "./fixtures.js";

/** One AI-SDK frame as it arrives on the wire. */
function frame(type: string, extra: Record<string, unknown> = {}): NovaFrame {
  return { type, sequence: undefined, payload: { type, ...extra } };
}

/** Replays a scripted frame list, so ordering is the only variable. */
class ReplayNova implements NovaLike {
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

interface Harness {
  readonly bubbles: string[];
  turn(frames: readonly NovaFrame[]): Promise<readonly string[]>;
}

async function harness(): Promise<Harness> {
  const dir = await mkdtemp(join(tmpdir(), "nova-narration-"));
  const config: BridgeConfig = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    currentAgentPath: join(dir, "current.json"),
    spillDir: join(dir, "out"),
    outboxDir: join(dir, "outbox"),
    // Long enough that nothing is flushed on a timer: every bubble here is sent
    // deliberately, so a test cannot pass by accident.
    progressIntervalMs: 100_000,
    stillWorkingMs: 100_000,
  };
  const sessions = new SessionStore(config.statePath);
  await sessions.load();
  const current = new CurrentAgentStore(config.currentAgentPath);
  await current.load();

  const bubbles: string[] = [];
  const capture = (message: string | ChatResponse): void => {
    bubbles.push(typeof message === "string" ? message : (message.text ?? ""));
  };

  return {
    bubbles,
    turn: async (frames) => {
      bubbles.length = 0;
      // A fresh agent per turn so the store and the gate start clean; the point
      // of the test is the order frames are turned into bubbles, not accumulation.
      const agent = new WeixinNovaAgent(
        config,
        new ReplayNova(frames),
        sessions,
        null,
        undefined,
        { currentAgents: current },
      );
      agent.attachBot({
        sendMessage: async (message: string | ChatResponse) => {
          capture(message);
        },
        wait: async () => undefined,
      } as unknown as Bot);
      await agent.chat({ conversationId: "u1", text: "查一下北京必吃的小吃" });
      await agent.whenIdle();
      return bubbles;
    },
  };
}

/** The captured turn: narrate, search twice, then answer. */
const CAPTURED: readonly NovaFrame[] = [
  frame("data-nova-session", { data: { sessionId: "sess-1" } }),
  frame("start"),
  frame("start-step"),
  frame("text-start", { id: "t0" }),
  frame("text-delta", { id: "t0", delta: "我搜" }),
  frame("text-delta", { id: "t0", delta: "一下。" }),
  frame("text-end", { id: "t0" }),
  frame("tool-input-start", { toolName: "web_search" }),
  frame("tool-input-available", {
    toolName: "web_search",
    input: { query: "北京必吃小吃 2026 老字号 排行" },
  }),
  frame("tool-output-available", { toolName: "web_search" }),
  frame("tool-input-available", {
    toolName: "web_search",
    input: { query: "北京小吃排行 豆汁 焦圈" },
  }),
  frame("tool-output-available", { toolName: "web_search" }),
  frame("finish-step"),
  frame("start-step"),
  frame("text-start", { id: "t1" }),
  frame("text-delta", { id: "t1", delta: "老字号里这几家最稳。" }),
  frame("text-end", { id: "t1" }),
  frame("finish-step"),
  frame("finish"),
  frame("[DONE]"),
];

describe("narration before the tool call it explains", () => {
  it("puts the model's words ahead of the tool lines", async () => {
    const h = await harness();

    const bubbles = await h.turn(CAPTURED);

    // Compared as offsets in the whole stream, not as bubble indices: the
    // narration and the tool lines it introduces share one progress bubble, so
    // the ordering that matters is within it.
    const stream = bubbles.join("\n");
    const spoken = stream.indexOf("我搜一下。");
    const firstTool = stream.indexOf("→ web_search");
    assert.ok(spoken >= 0, `the narration was dropped: ${JSON.stringify(bubbles)}`);
    assert.ok(firstTool >= 0, `no tool line: ${JSON.stringify(bubbles)}`);
    assert.ok(
      spoken < firstTool,
      `narration must precede the tool call: ${JSON.stringify(bubbles)}`,
    );
  });

  it("keeps the narration in the same bubble as the tools it introduces", async () => {
    const h = await harness();

    const bubbles = await h.turn(CAPTURED);

    const progress = bubbles.find((bubble) => bubble.includes("我搜一下。"));
    assert.match(progress ?? "", /→ web_search/);
    assert.match(progress ?? "", /→ web_search/, "both searches are listed");
  });

  it("sends the final answer once, without repeating the narration", async () => {
    const h = await harness();

    const bubbles = await h.turn(CAPTURED);

    const answers = bubbles.filter((bubble) =>
      bubble.includes("老字号里这几家最稳。"),
    );
    assert.equal(answers.length, 1, `answered once: ${JSON.stringify(bubbles)}`);
    assert.ok(
      bubbles.every((bubble) => !bubble.includes("没有返回内容")),
      `no empty-result complaint: ${JSON.stringify(bubbles)}`,
    );
  });

  it("does not repeat narration when the turn ends right after the tool", async () => {
    // The stream can end on the tool result. Reporting "没有返回内容" there
    // would be wrong -- the turn did say something -- but re-sending the same
    // words as a closing line would be noise.
    const h = await harness();
    const cutShort = CAPTURED.slice(0, 11);

    const bubbles = await h.turn(cutShort);

    const spoken = bubbles.filter((bubble) => bubble.includes("我搜一下。"));
    assert.equal(spoken.length, 1, `said once: ${JSON.stringify(bubbles)}`);
    assert.ok(
      bubbles.every((bubble) => !bubble.includes("没有返回内容")),
      `no empty-result complaint: ${JSON.stringify(bubbles)}`,
    );
  });

  it("says nothing extra when a turn has no narration at all", async () => {
    const h = await harness();
    const noNarration = CAPTURED.filter(
      (item) => item.type !== "text-start" && item.type !== "text-end" && item.type !== "text-delta",
    );

    const bubbles = await h.turn(noNarration);

    assert.equal(
      bubbles.filter((bubble) => bubble.startsWith("我搜")).length,
      0,
      `no invented narration: ${JSON.stringify(bubbles)}`,
    );
  });
});
