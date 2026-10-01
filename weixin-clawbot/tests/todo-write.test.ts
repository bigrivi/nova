/**
 * A `todo_write` call reaches the user as a readable plan.
 *
 * The call carries the whole list every time, so it is the plan rather than a
 * step, and on a long turn it is the thing a user watches to judge whether the
 * work is going the right way. `describeToolCall` cannot help: the payload is a
 * list of objects, so it fell through to the unlisted-tool fallback and produced
 * a bare "→ todo_write" with the plan nowhere in it.
 *
 * The payload shape below is the one `nova/tools/todo_write.py` declares.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { describeTodoWrite } from "../src/nova.js";

/** A real capture: content, status and priority, as the schema requires. */
const PLAN = {
  todos: [
    { content: "分析 CSV 找出最多的城市", status: "in_progress", priority: "high" },
    { content: "画柱状图", status: "pending", priority: "medium" },
    { content: "写结论报告", status: "pending", priority: "low" },
  ],
};

describe("describeTodoWrite", () => {
  it("renders the plan with a marker per status", () => {
    assert.deepEqual(describeTodoWrite(PLAN), [
      "[>] 分析 CSV 找出最多的城市",
      "[ ] 画柱状图",
      "[ ] 写结论报告",
    ]);
  });

  it("marks every status the schema allows", () => {
    const lines = describeTodoWrite({
      todos: [
        { content: "做完了", status: "completed", priority: "low" },
        { content: "在做", status: "in_progress", priority: "high" },
        { content: "还没开始", status: "pending", priority: "medium" },
        { content: "不做了", status: "cancelled", priority: "low" },
      ],
    });

    assert.deepEqual(lines, [
      "[x] 做完了",
      "[>] 在做",
      "[ ] 还没开始",
      "[-] 不做了",
    ]);
  });

  it("reads as a scannable plan, not a log of a payload", () => {
    // The regression: the old output was a single empty summary, so the bubble
    // said only that a tool had been called.
    assert.notDeepEqual(describeTodoWrite(PLAN), []);
    assert.equal(describeTodoWrite(PLAN).length, 3);
  });

  it("leaves priority out of the line", () => {
    // Priority is the agent's own ordering, already implied by the order of the
    // list; a marker column on top of a checkbox column is noise in a chat
    // bubble.
    const lines = describeTodoWrite({
      todos: [{ content: "只有一条", status: "pending", priority: "high" }],
    });

    assert.deepEqual(lines, ["[ ] 只有一条"]);
  });

  it("falls back to pending for a status the schema does not define", () => {
    const lines = describeTodoWrite({
      todos: [{ content: "状态写错了", status: "wat", priority: "high" }],
    });

    assert.deepEqual(lines, ["[ ] 状态写错了"]);
  });

  it("treats a missing status as pending", () => {
    const lines = describeTodoWrite({
      todos: [{ content: "没写状态", priority: "low" }],
    });

    assert.deepEqual(lines, ["[ ] 没写状态"]);
  });

  it("returns nothing for a payload it cannot read", () => {
    for (const input of [
      undefined,
      null,
      "todos",
      {},
      { todos: [] },
      { todos: "nope" },
      { todos: [null, 7] },
      { todos: [{ status: "pending" }] },
      { todos: [{ content: "   " }] },
    ]) {
      assert.deepEqual(
        describeTodoWrite(input),
        [],
        `${JSON.stringify(input)} must render nothing`,
      );
    }
  });
});
