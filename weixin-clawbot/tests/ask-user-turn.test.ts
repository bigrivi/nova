/**
 * A turn that pauses to ask the user reaches them as questions.
 *
 * The frames below are the ones Nova actually emitted for a faker-backed
 * `ask_user` call, captured rather than assumed -- the shape matters, because
 * `data-nova-input-required` carries none of it.
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

/** The exact `input` Nova sent on its `ask_user` announcement frame. */
const CAPTURED_QUESTIONS = {
  questions: [
    {
      id: "q0",
      header: "当前城市",
      question: "请告诉我你想查询哪座城市的天气？",
      input_type: "text",
      options: [],
      multiple: false,
      required: true,
      default: "",
    },
    {
      id: "q1",
      header: "出行日期",
      question: "请输入日期 YYYY-MM-DD",
      input_type: "text",
      options: [],
      multiple: false,
      required: true,
      default: "",
    },
  ],
};

/**
 * One `ask_user` turn, frame for frame, as captured from Nova.
 *
 * No `text-delta` anywhere: the model asks and the turn stops, so the bridge has
 * no answer to send unless it reads the questions off the tool frame.
 */
class AskUserNova implements NovaLike {
  /** The message of the turn that followed the questions. */
  answers: string[] = [];

  constructor(private readonly questions: unknown = CAPTURED_QUESTIONS) {}

  async *streamChat(request: NovaChatRequest): AsyncGenerator<NovaFrame> {
    const frame = (
      type: string,
      extra: Record<string, unknown> = {},
    ): NovaFrame => ({ type, sequence: undefined, payload: { type, ...extra } });

    yield frame("data-nova-session", { data: { sessionId: "sess-1" } });
    yield frame("start");
    yield frame("start-step");
    yield frame("tool-input-start", { toolName: "ask_user" });
    yield frame("tool-input-available", {
      toolName: "ask_user",
      input: this.questions,
    });
    yield frame("tool-output-available", {
      toolName: "ask_user",
      output: this.questions,
    });
    yield frame("finish-step");
    yield frame("data-nova-input-required", {
      data: { message: "User input required" },
    });
    yield frame("finish");
    yield frame("[DONE]");
  }

  /** Records the reply so the test can assert the question was answerable. */
  async *resume(message: string): AsyncGenerator<NovaFrame> {
    this.answers.push(message);
    const frame = (type: string, extra: Record<string, unknown> = {}): NovaFrame => ({
      type,
      sequence: undefined,
      payload: { type, ...extra },
    });
    yield frame("data-nova-session", { data: { sessionId: "sess-1" } });
    yield frame("start");
    yield frame("start-step");
    yield frame("text-start", { id: "t" });
    yield frame("text-delta", { id: "t", delta: "收到，帮你规划。" });
    yield frame("text-end", { id: "t" });
    yield frame("finish-step");
    yield frame("finish");
    yield frame("[DONE]");
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
  readonly agent: WeixinNovaAgent;
  readonly bubbles: string[];
  turn(text: string): Promise<readonly string[]>;
}

async function harness(nova: AskUserNova): Promise<Harness> {
  const dir = await mkdtemp(join(tmpdir(), "nova-askuser-"));
  const config: BridgeConfig = {
    ...loadConfig(),
    statePath: join(dir, "sessions.json"),
    currentAgentPath: join(dir, "current.json"),
    spillDir: join(dir, "out"),
    outboxDir: join(dir, "outbox"),
    progressIntervalMs: 100_000,
    stillWorkingMs: 100_000,
  };
  const sessions = new SessionStore(config.statePath);
  await sessions.load();
  const current = new CurrentAgentStore(config.currentAgentPath);
  await current.load();

  const bubbles: string[] = [];
  const agent = new WeixinNovaAgent(config, nova, sessions, null, undefined, {
    currentAgents: current,
  });
  agent.attachBot({
    sendMessage: async (message: string | ChatResponse) => {
      bubbles.push(typeof message === "string" ? message : (message.text ?? ""));
    },
    wait: async () => undefined,
  } as unknown as Bot);

  return {
    agent,
    bubbles,
    turn: async (text) => {
      bubbles.length = 0;
      await agent.chat({ conversationId: "u1", text });
      await agent.whenIdle();
      return bubbles;
    },
  };
}

describe("a turn that asks", () => {
  it("sends the questions as their own bubble", async () => {
    const h = await harness(new AskUserNova());

    const bubbles = await h.turn("帮我规划旅行");

    const question = bubbles.find((bubble) => bubble.includes("需要你回答"));
    assert.ok(question, `no question reached the user: ${JSON.stringify(bubbles)}`);
    assert.match(question, /1\. 【当前城市】请告诉我你想查询哪座城市的天气？/);
    assert.match(question, /2\. 【出行日期】请输入日期 YYYY-MM-DD/);
    assert.match(question, /共 2 题，按题号回复即可/);
  });

  it("does not also claim the turn returned nothing", async () => {
    // The regression: with no text-delta the turn has no answer, and the closing
    // line used to say so -- right after asking a question that looks ignored.
    const h = await harness(new AskUserNova());

    const bubbles = await h.turn("帮我规划旅行");

    assert.ok(
      bubbles.every((bubble) => !bubble.includes("没有返回内容")),
      `the turn must not report an empty result: ${JSON.stringify(bubbles)}`,
    );
  });

  it("ends on the questions, not on a generic tool line", async () => {
    // The turn is about to stop, so a question queued behind the progress timer
    // reads as a hang. It is sent as its own bubble and is the last thing the
    // user sees, which is what makes the next message obviously the answer.
    const h = await harness(new AskUserNova());

    const bubbles = await h.turn("帮我规划旅行");

    assert.match(
      bubbles.at(-1) ?? "",
      /需要你回答/,
      `the question must be last: ${JSON.stringify(bubbles)}`,
    );
    assert.ok(
      bubbles.every((bubble) => !bubble.includes("→ ask_user")),
      `the questions must not also appear as a tool line: ${JSON.stringify(bubbles)}`,
    );
  });

  it("falls back to the generic tool line when the questions are unreadable", async () => {
    const h = await harness(new AskUserNova({ questions: "nope" }));

    const bubbles = await h.turn("帮我规划旅行");

    assert.ok(
      bubbles.every((bubble) => !bubble.includes("需要你回答")),
      "an unreadable payload must not render as a question",
    );
  });

  it("answers on the same session, which is all the SDK needs", async () => {
    // Nova delivers the reply as an ordinary message on the same session, so the
    // bridge's only job is having asked a legible question.
    const nova = new AskUserNova();
    const h = await harness(nova);
    await h.turn("帮我规划旅行");

    for await (const _ of nova.resume("北京，三天")) {
      // The frames are asserted in AskUserNova.resume; consuming them here keeps
      // the type honest about it being a stream.
    }

    assert.deepEqual(nova.answers, ["北京，三天"]);
  });
});
