/**
 * `ask_user` reaches the user as actual questions.
 *
 * The questions arrive on the tool's `tool-input-available` frame.
 * `data-nova-input-required` carries only the string "User input required", so a
 * bridge that renders that frame has nothing to show -- the turn just stops and
 * the user is left with silence, which is what this file exists to prevent.
 *
 * The fixtures below are the frames Nova actually emitted, not a guess.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { describeAskUser } from "../src/nova.js";

/** The two questions Nova's faker produced for "帮我规划一次旅行，先问我几个问题". */
const CAPTURED_INPUT = {
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

describe("describeAskUser", () => {
  it("renders both captured questions, numbered for answering", () => {
    const lines = describeAskUser(CAPTURED_INPUT);

    assert.deepEqual(lines, [
      "1. 【当前城市】请告诉我你想查询哪座城市的天气？",
      "2. 【出行日期】请输入日期 YYYY-MM-DD",
    ]);
  });

  it("lists a select question's options unnumbered", () => {
    const lines = describeAskUser({
      questions: [
        {
          id: "q0",
          header: "目的地",
          question: "想去哪？",
          input_type: "select",
          options: [
            { label: "北京", description: "北方都市" },
            { label: "上海", description: "" },
          ],
          required: true,
        },
        {
          id: "q1",
          header: "预算",
          question: "预算多少？",
          input_type: "text",
          required: true,
        },
      ],
    });

    assert.deepEqual(lines, [
      "1. 【目的地】想去哪？",
      "   北京 —— 北方都市",
      "   上海",
      "2. 【预算】预算多少？",
    ]);
  });

  it("never numbers an option, so a reply cannot quote a number back", () => {
    // The regression: with "2.2" style options the model read a reply of
    // "2. 2.2" as the user pointing at a rendered line rather than choosing,
    // and reported "you sent the template number, not an answer".
    const lines = describeAskUser({
      questions: [
        {
          id: "goal",
          header: "主要目标",
          question: "主要想练什么？",
          input_type: "select",
          options: [
            { label: "减脂塑形", description: "有氧+团操课为主" },
            { label: "增肌力量", description: "自由重量区" },
          ],
          required: true,
        },
      ],
    });

    for (const line of lines.slice(1)) {
      assert.ok(
        !/^\s*[\d]+\s*[.、)）]|^\s*[a-zA-Z]\s*\)/.test(line),
        `option must be unnumbered: ${JSON.stringify(line)}`,
      );
    }
  });

  it("shows a textarea default as a template to fill in", () => {
    const lines = describeAskUser({
      questions: [
        {
          id: "q0",
          header: "背景",
          question: "介绍一下项目",
          input_type: "textarea",
          default: "项目名：\n目标：",
          required: true,
        },
      ],
    });

    assert.deepEqual(lines, [
      "1. 【背景】介绍一下项目",
      "   （默认：项目名：\n目标：）",
    ]);
  });

  it("marks an optional question, since answering it is not mandatory", () => {
    const lines = describeAskUser({
      questions: [
        { id: "q0", header: "备注", question: "还有别的吗？", required: false },
      ],
    });

    assert.deepEqual(lines, ["1. 【备注】还有别的吗？（可选）"]);
  });

  it("drops the header when the question text already says it", () => {
    // The header is a short label; repeating it verbatim is noise.
    const lines = describeAskUser({
      questions: [
        { id: "q0", header: "城市", question: "你想查哪座城市的天气？", required: true },
      ],
    });

    assert.deepEqual(lines, ["1. 【城市】你想查哪座城市的天气？"]);
  });

  it("falls back to the header when the question text is empty", () => {
    // An empty question with a header set is legal, and dropping the entry would
    // silently lose a question the model did intend to ask.
    const lines = describeAskUser({
      questions: [{ id: "q0", header: "城市", question: "", required: true }],
    });

    assert.deepEqual(lines, ["1. 城市"]);
  });

  it("drops numbering the model wrote into the question itself", () => {
    // Models frequently number the question inside `question`, and the bridge
    // adds its own. Left in place the user reads "1. 【城市】1. 你在哪？" and the
    // reply they type looks like it belongs to a different question.
    const lines = describeAskUser({
      questions: [
        { id: "q0", header: "城市", question: "1. 你在哪个城市/区域？", required: true },
        { id: "q1", header: "目标", question: "2、练什么？", required: true },
        { id: "q2", header: "预算", question: "3) 月预算？", required: true },
      ],
    });

    assert.deepEqual(lines, [
      "1. 【城市】你在哪个城市/区域？",
      "2. 【目标】练什么？",
      "3. 【预算】月预算？",
    ]);
  });

  it("keeps a question that genuinely starts with a number", () => {
    const lines = describeAskUser({
      questions: [
        { id: "q0", header: "年份", question: "2026 年的预算按多少算？", required: true },
      ],
    });

    assert.deepEqual(lines, ["1. 【年份】2026 年的预算按多少算？"]);
  });

  it("returns nothing for a payload it cannot read", () => {
    // Degrading to the generic tool line beats printing `[object Object]` into
    // the user's chat.
    for (const input of [
      undefined,
      null,
      "questions",
      {},
      { questions: [] },
      { questions: "nope" },
      { questions: [null, 3] },
      { questions: [{ id: "q0" }] },
    ]) {
      assert.deepEqual(
        describeAskUser(input),
        [],
        `${JSON.stringify(input)} must render nothing`,
      );
    }
  });
});
