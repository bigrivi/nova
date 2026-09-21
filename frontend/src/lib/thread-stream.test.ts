import type { ThreadMessageLike } from "@assistant-ui/react";
import { describe, expect, it } from "vitest";

import type { NovaStreamEvent } from "../types/nova";
import {
    applyStreamEvent,
    applyStreamEventOnce,
    describeStreamSideEffects,
    extractApprovalRequest,
    extractReasoningElapsedMs,
    extractSessionId,
    extractToolErrorCallId,
    mergeMessagesById,
    parseSseFrame,
    throwStreamError,
    upsertAssistantToolCall,
} from "./thread-stream";

const ASSISTANT_ID = "assistant-1";

function assistantMessage(
    content: ThreadMessageLike["content"] = [],
): ThreadMessageLike {
    return {
        id: ASSISTANT_ID,
        role: "assistant",
        content,
        createdAt: new Date(0),
    };
}

function userMessage(): ThreadMessageLike {
    return {
        id: "user-1",
        role: "user",
        content: "hello",
        createdAt: new Date(0),
    };
}

function partsOf(message: ThreadMessageLike) {
    return typeof message.content === "string" ? [] : [...message.content];
}

function textOf(message: ThreadMessageLike): string {
    return partsOf(message)
        .filter((part) => part.type === "text")
        .map((part) => (part.type === "text" ? part.text : ""))
        .join("");
}

function reasoningOf(message: ThreadMessageLike) {
    return partsOf(message).filter((part) => part.type === "reasoning");
}

function toolCallOf(message: ThreadMessageLike, toolCallId: string) {
    return partsOf(message).find(
        (part) => part.type === "tool-call" && part.toolCallId === toolCallId,
    );
}

describe("applyStreamEvent text branches", () => {
    it("appends an empty text part on text-start", () => {
        const next = applyStreamEvent(
            [userMessage(), assistantMessage()],
            { type: "text-start" },
            { assistantMessageId: ASSISTANT_ID },
        );

        expect(next[0]).toEqual(userMessage());
        const textParts = partsOf(next[1]!).filter(
            (part) => part.type === "text",
        );
        expect(textParts).toHaveLength(1);
        expect(textParts[0]).toEqual({ type: "text", text: "" });
    });

    it("appends delta text on text-delta", () => {
        const next = applyStreamEvent(
            [assistantMessage([{ type: "text", text: "hel" }])],
            { type: "text-delta", delta: "lo" },
            { assistantMessageId: ASSISTANT_ID },
        );

        expect(textOf(next[0]!)).toBe("hello");
    });

    it("converts string content to parts on text-delta", () => {
        const before: ThreadMessageLike[] = [
            { ...assistantMessage(), content: "hel" },
        ];
        const next = applyStreamEvent(
            before,
            { type: "text-delta", delta: "lo" },
            { assistantMessageId: ASSISTANT_ID },
        );

        expect(textOf(next[0]!)).toBe("hello");
    });

    it("ignores messages with a different id", () => {
        const before = [assistantMessage([{ type: "text", text: "x" }])];
        const next = applyStreamEvent(
            before,
            { type: "text-delta", delta: "y" },
            { assistantMessageId: "other" },
        );

        expect(textOf(next[0]!)).toBe("x");
    });
});

describe("applyStreamEvent reasoning branches", () => {
    it("starts reasoning, accumulates deltas, and stamps elapsedMs", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        let messages = applyStreamEvent(
            [assistantMessage()],
            { type: "reasoning-start" },
            context,
        );
        expect(reasoningOf(messages[0]!)).toHaveLength(1);

        messages = applyStreamEvent(
            messages,
            { type: "reasoning-delta", delta: "think" },
            context,
        );
        messages = applyStreamEvent(
            messages,
            { type: "reasoning-delta", delta: "ing" },
            context,
        );
        const reasoning = reasoningOf(messages[0]!);
        expect(reasoning).toHaveLength(1);
        expect(reasoning[0]?.type === "reasoning" && reasoning[0].text).toBe(
            "thinking",
        );

        messages = applyStreamEvent(
            messages,
            { type: "reasoning-end", elapsedMs: 1200 },
            context,
        );
        const stamped = reasoningOf(messages[0]!)[0];
        expect(
            stamped?.type === "reasoning" &&
                (stamped as { elapsedMs?: number }).elapsedMs,
        ).toBe(1200);
    });

    it("returns messages unchanged when reasoning-end has no elapsedMs", () => {
        const before = [assistantMessage()];
        const next = applyStreamEvent(
            before,
            { type: "reasoning-end" },
            { assistantMessageId: ASSISTANT_ID },
        );

        expect(next).toBe(before);
    });
});

describe("applyStreamEvent tool branches", () => {
    it("upserts tool input via upsertAssistantToolCall on tool-input-start/available", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        let messages = applyStreamEvent(
            [assistantMessage()],
            {
                type: "tool-input-start",
                toolCallId: "call-1",
                toolName: "read",
            },
            context,
        );
        let part = toolCallOf(messages[0]!, "call-1");
        expect(part?.type === "tool-call" && part.toolName).toBe("read");

        messages = applyStreamEvent(
            messages,
            {
                type: "tool-input-available",
                toolCallId: "call-1",
                toolName: "read",
                input: { path: "a.ts" },
            },
            context,
        );
        part = toolCallOf(messages[0]!, "call-1");
        expect(part?.type === "tool-call" && part.args).toEqual({
            path: "a.ts",
        });
        expect(part?.type === "tool-call" && part.argsText).toBe(
            JSON.stringify({ path: "a.ts" }),
        );
    });

    it("upserts tool output without dropping args", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        let messages = applyStreamEvent(
            [assistantMessage()],
            {
                type: "tool-input-available",
                toolCallId: "call-1",
                toolName: "read",
                input: { path: "a.ts" },
            },
            context,
        );
        messages = applyStreamEvent(
            messages,
            {
                type: "tool-output-available",
                toolCallId: "call-1",
                output: { content: "ok" },
            },
            context,
        );

        const part = toolCallOf(messages[0]!, "call-1");
        expect(part?.type === "tool-call" && part.result).toEqual({
            content: "ok",
        });
        expect(part?.type === "tool-call" && part.args).toEqual({
            path: "a.ts",
        });
    });

    it("marks tool error without dropping the tool name", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        let messages = applyStreamEvent(
            [assistantMessage()],
            {
                type: "tool-input-available",
                toolCallId: "call-9",
                toolName: "shell",
                input: { command: "ls" },
            },
            context,
        );
        messages = applyStreamEvent(
            messages,
            {
                type: "data-nova-tool-error",
                data: { toolCallId: "call-9" },
            } as NovaStreamEvent,
            context,
        );

        const part = toolCallOf(messages[0]!, "call-9");
        expect(part?.type === "tool-call" && part.isError).toBe(true);
        expect(part?.type === "tool-call" && part.toolName).toBe("shell");
    });

    it("returns messages unchanged when tool ids are missing", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        const cases: NovaStreamEvent[] = [
            { type: "tool-input-start" },
            { type: "tool-input-available" },
            { type: "tool-output-available" },
            { type: "data-nova-tool-error", data: {} },
        ];
        for (const event of cases) {
            const before = [assistantMessage()];
            expect(applyStreamEvent(before, event, context)).toBe(before);
        }
    });

    it("upsertAssistantToolCall defaults a missing tool name to tool", () => {
        const next = upsertAssistantToolCall([assistantMessage()], ASSISTANT_ID, {
            toolCallId: "call-x",
        });

        const part = toolCallOf(next[0]!, "call-x");
        expect(part?.type === "tool-call" && part.toolName).toBe("tool");
    });
});

describe("applyStreamEvent non-patch branches", () => {
    it("leaves messages untouched for session/compaction/heartbeat/approval/input-required/unknown events", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        const cases: NovaStreamEvent[] = [
            { type: "data-nova-session", data: { sessionId: "s-1" } },
            { type: "data-nova-compaction-start" },
            { type: "data-nova-compaction-end" },
            { type: "data-nova-heartbeat" },
            {
                type: "data-nova-approval-required",
                data: { requestId: "r", command: "c", description: "d" },
            },
            { type: "data-nova-input-required" },
            { type: "something-else" },
        ];
        for (const event of cases) {
            const before = [assistantMessage([{ type: "text", text: "x" }])];
            expect(applyStreamEvent(before, event, context)).toBe(before);
        }
    });

    it("throws the stream error for error events", () => {
        expect(() =>
            applyStreamEvent(
                [assistantMessage()],
                { type: "error", errorText: "boom" },
                { assistantMessageId: ASSISTANT_ID },
            ),
        ).toThrow("boom");
    });

    it("throwStreamError falls back to Unknown error", () => {
        expect(() => throwStreamError({ type: "error" })).toThrow(
            "Unknown error",
        );
    });

    it("throwStreamError is non-retryable so the frame is shown, not resumed past", () => {
        try {
            throwStreamError({ type: "error", errorText: "HTTP 429" });
            throw new Error("expected throwStreamError to throw");
        } catch (error) {
            expect((error as Error).message).toBe("HTTP 429");
            expect(
                (error as Error & { retryable?: boolean }).retryable,
            ).toBe(false);
        }
    });
});

describe("event extractors", () => {
    it("extracts session, tool-error, elapsed, and approval payloads", () => {
        expect(
            extractSessionId({
                type: "data-nova-session",
                data: { sessionId: "s-1" },
            }),
        ).toBe("s-1");
        expect(extractSessionId({ type: "data-nova-session" })).toBe("");
        expect(
            extractToolErrorCallId({
                type: "data-nova-tool-error",
                data: { toolCallId: "call-9" },
            } as NovaStreamEvent),
        ).toBe("call-9");
        expect(
            extractToolErrorCallId({ type: "data-nova-tool-error" }),
        ).toBe("");
        expect(
            extractReasoningElapsedMs({ type: "reasoning-end", elapsedMs: 5 }),
        ).toBe(5);
        expect(extractReasoningElapsedMs({ type: "reasoning-end" })).toBeNull();
        expect(
            extractApprovalRequest({
                type: "data-nova-approval-required",
                data: { requestId: "r", command: "c", description: "d" },
            }),
        ).toEqual({ requestId: "r", command: "c", description: "d" });
    });
});

describe("parseSseFrame", () => {
    it("parses the id prefix and joins data lines", () => {
        expect(
            parseSseFrame('id: 12\ndata: {"type":"text-delta"}'),
        ).toEqual({ sequence: 12, payload: '{"type":"text-delta"}' });
    });

    it("joins multi-line data payloads", () => {
        expect(parseSseFrame("id: 3\ndata: line-one\ndata: line-two")).toEqual(
            { sequence: 3, payload: "line-one\nline-two" },
        );
    });

    it("returns no payload for [DONE] but keeps the sequence", () => {
        expect(parseSseFrame("id: 9\ndata: [DONE]")).toEqual({
            sequence: 9,
            payload: null,
        });
    });

    it("tolerates missing or invalid id lines", () => {
        expect(parseSseFrame('data: {"type":"x"}')).toEqual({
            sequence: null,
            payload: '{"type":"x"}',
        });
        expect(parseSseFrame('id: nope\ndata: {"type":"x"}')).toEqual({
            sequence: null,
            payload: '{"type":"x"}',
        });
        expect(parseSseFrame("id: 0\ndata: [DONE]")).toEqual({
            sequence: null,
            payload: null,
        });
    });
});

describe("applyStreamEventOnce", () => {
    it("applies a sequenced delta exactly once across replays", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        const seen = new Set<number>();
        const start = [assistantMessage([{ type: "text", text: "" }])];

        const first = applyStreamEventOnce(
            start,
            { type: "text-delta", delta: "he", sequence: 4 },
            context,
            seen,
        );
        expect(first.applied).toBe(true);
        expect(textOf(first.messages[0]!)).toBe("he");

        const replay = applyStreamEventOnce(
            first.messages,
            { type: "text-delta", delta: "he", sequence: 4 },
            context,
            seen,
        );
        expect(replay.applied).toBe(false);
        expect(replay.messages).toBe(first.messages);
        expect(textOf(replay.messages[0]!)).toBe("he");

        const next = applyStreamEventOnce(
            replay.messages,
            { type: "text-delta", delta: "llo", sequence: 5 },
            context,
            seen,
        );
        expect(next.applied).toBe(true);
        expect(textOf(next.messages[0]!)).toBe("hello");
    });

    it("applies unsequenced events every time for older backends", () => {
        const context = { assistantMessageId: ASSISTANT_ID };
        const seen = new Set<number>();
        const start = [assistantMessage([{ type: "text", text: "" }])];
        const first = applyStreamEventOnce(
            start,
            { type: "text-delta", delta: "x" },
            context,
            seen,
        );
        const second = applyStreamEventOnce(
            first.messages,
            { type: "text-delta", delta: "y" },
            context,
            seen,
        );
        expect(textOf(second.messages[0]!)).toBe("xy");
    });
});

describe("mergeMessagesById", () => {
    it("appends only messages with unseen ids", () => {
        const resumed: ThreadMessageLike = {
            id: "assistant-2",
            role: "assistant",
            content: [{ type: "text", text: "new" }],
            createdAt: new Date(0),
        };
        const merged = mergeMessagesById(
            [userMessage(), assistantMessage()],
            [userMessage(), resumed],
        );
        expect(merged).toHaveLength(3);
        expect(textOf(merged[2]!)).toBe("new");
    });

    it("returns the existing array when nothing is fresh", () => {
        const existing = [userMessage()];
        expect(mergeMessagesById(existing, [userMessage()])).toBe(existing);
        expect(mergeMessagesById(existing, [])).toBe(existing);
    });
});

describe("describeStreamSideEffects", () => {
    it("reports ask-user and todo inputs for tool-input-available", () => {
        expect(
            describeStreamSideEffects({
                type: "tool-input-available",
                toolCallId: "call-1",
                toolName: "ask_user",
                input: { q: 1 },
            }),
        ).toEqual([{ kind: "ask-user", input: { q: 1 } }]);

        expect(
            describeStreamSideEffects({
                type: "tool-input-available",
                toolCallId: "call-2",
                toolName: "todo_write",
                input: { todos: [] },
            }),
        ).toEqual([{ kind: "todo-active", input: { todos: [] } }]);
    });

    it("returns no effects for other tools or missing call ids", () => {
        expect(
            describeStreamSideEffects({
                type: "tool-input-available",
                toolCallId: "call-3",
                toolName: "read",
                input: {},
            }),
        ).toEqual([]);
        expect(
            describeStreamSideEffects({
                type: "tool-input-available",
                toolName: "ask_user",
            }),
        ).toEqual([]);
        expect(describeStreamSideEffects({ type: "text-delta", delta: "x" })).toEqual(
            [],
        );
    });
});
