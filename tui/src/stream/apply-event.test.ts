import { describe, expect, test } from "bun:test";
import type { NovaStreamEvent } from "../api/types.ts";
import type { ApprovalPending } from "../stores/approval-store.ts";
import {
    applyStreamEvent,
    parseAskQuestions,
    parseContextEvent,
    type StreamAccumulator,
    type StreamEffects,
} from "./apply-event.ts";

function makeEffects(overrides: Partial<StreamEffects> = {}) {
    const calls: string[] = [];
    let sessionId: string | null = "s1";
    let approval: ApprovalPending | null = null;
    const effects: StreamEffects = {
        runId: 7,
        getSessionId: () => sessionId,
        setSessionId: (id) => {
            sessionId = id;
            calls.push(`session:${id}`);
        },
        markOwnActive: (id) => calls.push(`own:${id}`),
        getApproval: () => approval,
        setApproval: (pending) => {
            approval = pending;
            calls.push(pending ? `approval:${pending.requestId}` : "approval:null");
        },
        setAskActive: (questions) =>
            calls.push(`ask:${questions?.length ?? "null"}`),
        setCtx: (used, limit, percent) =>
            calls.push(`ctx:${used}/${limit}/${percent}`),
        setTodos: () => calls.push("todos"),
        startCompaction: (messages, tokens) =>
            calls.push(`compaction-start:${messages}/${tokens}`),
        endCompaction: () => calls.push("compaction-end"),
        setPending: (id, pending) => calls.push(`pending:${id}:${pending}`),
        insertWakeMessage: (text, wakeFor) =>
            calls.push(`wake:${text}:${wakeFor}`),
        startTextPart: (id) => calls.push(`text-start:${id}`),
        appendTextDelta: (id, delta) => calls.push(`text:${id}:${delta}`),
        startReasoningPart: (id) => calls.push(`reasoning-start:${id}`),
        appendReasoningDelta: (id, delta) => calls.push(`reasoning:${id}:${delta}`),
        endReasoningPart: (id, elapsed) => calls.push(`reasoning-end:${id}:${elapsed}`),
        startToolCall: (id, tool) =>
            calls.push(`tool:${id}:${tool.toolName}:${tool.toolCallId}`),
        setToolInput: (id, callId, input) =>
            calls.push(`tool-input:${id}:${callId}:${JSON.stringify(input)}`),
        setToolOutput: (id, callId, output) =>
            calls.push(`tool-output:${id}:${callId}:${JSON.stringify(output)}`),
        setToolStatus: (id, callId, status) =>
            calls.push(`tool-status:${id}:${callId}:${status}`),
        failToolCall: (id, callId, message) =>
            calls.push(`tool-fail:${id}:${callId}:${message}`),
        ...overrides,
    };
    return { effects, calls };
}

function run(
    event: NovaStreamEvent,
    effects: StreamEffects,
    acc: StreamAccumulator = { askQuestions: null },
) {
    applyStreamEvent(event, "m1", effects, acc);
    return acc;
}

describe("parseAskQuestions", () => {
    test("accepts a questions array", () => {
        const [question] = parseAskQuestions({
            questions: [
                {
                    id: "q1",
                    header: "H",
                    question: "Q?",
                    input_type: "select",
                    options: [{ label: "A" }, { label: "B", value: "b" }],
                    multiple: true,
                },
            ],
        });
        expect(question?.id).toBe("q1");
        expect(question?.inputType).toBe("select");
        expect(question?.options.map((o) => o.label)).toEqual(["A", "B"]);
        expect(question?.multiple).toBe(true);
    });

    test("accepts a single question object", () => {
        const [question] = parseAskQuestions({
            question: { question: "Q?" },
        });
        expect(question?.id).toBe("q0");
        expect(question?.inputType).toBe("text");
    });

    test("rejects non-objects", () => {
        expect(parseAskQuestions(null)).toEqual([]);
        expect(parseAskQuestions("x")).toEqual([]);
    });
});

describe("parseContextEvent", () => {
    test("reads the data envelope", () => {
        expect(
            parseContextEvent({
                type: "data-nova-context",
                data: { used: 10, limit: 100, percent: 10 },
            }),
        ).toEqual({ used: 10, limit: 100, percent: 10 });
    });

    test("derives the percent when absent", () => {
        expect(
            parseContextEvent({
                type: "data-nova-context",
                data: { used: 25, limit: 100 },
            }),
        ).toEqual({ used: 25, limit: 100, percent: 25 });
    });
});

describe("applyStreamEvent", () => {
    test("records a new session and marks it own", () => {
        const { effects, calls } = makeEffects();
        run({ type: "data-nova-session", data: { sessionId: "s2" } }, effects);
        expect(calls).toEqual(["session:s2", "own:s2"]);
    });

    test("does not re-set the same session", () => {
        const { effects, calls } = makeEffects();
        run({ type: "data-nova-session", data: { sessionId: "s1" } }, effects);
        expect(calls).toEqual(["own:s1"]);
    });

    test("inserts a wake message", () => {
        const { effects, calls } = makeEffects();
        run(
            {
                type: "data-nova-wake",
                data: { text: "done", messageId: "job1" },
            },
            effects,
        );
        expect(calls).toEqual(["wake:done:job1"]);
    });

    test("routes text and reasoning deltas", () => {
        const { effects, calls } = makeEffects();
        run({ type: "text-start" }, effects);
        run({ type: "text-delta", delta: "hi" }, effects);
        run({ type: "reasoning-start" }, effects);
        run({ type: "reasoning-delta", delta: "why" }, effects);
        run({ type: "reasoning-end", elapsedMs: 12 }, effects);
        expect(calls).toEqual([
            "text-start:m1",
            "text:m1:hi",
            "reasoning-start:m1",
            "reasoning:m1:why",
            "reasoning-end:m1:12",
        ]);
    });

    test("tracks tool calls and failures", () => {
        const { effects, calls } = makeEffects();
        run(
            { type: "tool-input-start", toolCallId: "t1", toolName: "read" },
            effects,
        );
        run(
            {
                type: "tool-input-available",
                toolCallId: "t1",
                input: { filePath: "x" },
            },
            effects,
        );
        run(
            { type: "tool-output-available", toolCallId: "t1", output: "ok" },
            effects,
        );
        run(
            {
                type: "data-nova-tool-error",
                data: { toolCallId: "t1", message: "bad" },
            },
            effects,
        );
        expect(calls).toEqual([
            "tool:m1:read:t1",
            'tool-input:m1:t1:{"filePath":"x"}',
            'tool-output:m1:t1:"ok"',
            "tool-fail:m1:t1:bad",
        ]);
    });

    test("accumulates ask_user questions until input-required", () => {
        const { effects, calls } = makeEffects();
        const acc = run(
            {
                type: "tool-input-available",
                toolCallId: "t1",
                toolName: "ask_user",
                input: { questions: [{ question: "Q?" }] },
            },
            effects,
        );
        expect(acc.askQuestions).toHaveLength(1);
        run({ type: "data-nova-input-required" }, effects, acc);
        expect(calls).toEqual([
            'tool-input:m1:t1:{"questions":[{"question":"Q?"}]}',
            "ask:1",
        ]);
    });

    test("reports todo_write to the todo effect", () => {
        const { effects, calls } = makeEffects();
        run(
            {
                type: "tool-input-available",
                toolCallId: "t1",
                toolName: "todo_write",
                input: { todos: [] },
            },
            effects,
        );
        expect(calls).toContain("todos");
    });

    test("builds an approval with defaults", () => {
        const { effects, calls } = makeEffects();
        run(
            {
                type: "data-nova-approval-required",
                data: {
                    requestId: "r1",
                    command: "rm -rf dist",
                    toolCallId: "t1",
                    dangerous: true,
                },
            },
            effects,
        );
        expect(calls).toEqual(["approval:r1", "tool-status:m1:t1:blocked"]);
    });

    test("clears only the matching approval", () => {
        const { effects, calls } = makeEffects();
        run(
            { type: "data-nova-approval-required", data: { requestId: "r1" } },
            effects,
        );
        run(
            { type: "data-nova-approval-resolved", data: { requestId: "r0" } },
            effects,
        );
        run(
            { type: "data-nova-approval-resolved", data: { requestId: "r1" } },
            effects,
        );
        expect(calls).toEqual([
            "approval:r1",
            "approval:null",
        ]);
    });

    test("routes context and compaction events", () => {
        const { effects, calls } = makeEffects();
        run(
            {
                type: "data-nova-context",
                data: { used: 5, limit: 10, percent: 50 },
            },
            effects,
        );
        run(
            {
                type: "data-nova-compaction-start",
                data: { message_count: 2, token_count: 100 },
            },
            effects,
        );
        run({ type: "data-nova-compaction-end" }, effects);
        expect(calls).toEqual([
            "ctx:5/10/50",
            "compaction-start:2/100",
            "compaction-end",
        ]);
    });

    test("throws on an error event", () => {
        const { effects } = makeEffects();
        expect(() =>
            run({ type: "error", errorText: "boom" }, effects),
        ).toThrow("boom");
    });

    test("ignores unknown events", () => {
        const { effects, calls } = makeEffects();
        run({ type: "data-nova-heartbeat" }, effects);
        run({ type: "finish" }, effects);
        expect(calls).toEqual([]);
    });
});
