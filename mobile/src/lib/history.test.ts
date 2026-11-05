import { describe, expect, test } from "bun:test";

import type { NovaMessageRecord } from "../api/types";
import { recordsToMessages } from "./history";

function record(
    value: Partial<NovaMessageRecord> & Pick<NovaMessageRecord, "id" | "role">,
): NovaMessageRecord {
    return {
        session_id: "s1",
        content: "",
        tool_call_id: null,
        tool_calls: [],
        time_created: 0,
        ...value,
    };
}

describe("history mapping", () => {
    test("a user turn uses display_text when present", () => {
        const messages = recordsToMessages([
            record({
                id: "u1",
                role: "user",
                content: "Attached file: x",
                display_text: "what is this?",
            }),
        ]);
        expect(messages).toHaveLength(1);
        expect(messages[0]!.parts).toEqual([
            { type: "text", text: "what is this?" },
        ]);
    });

    test("user images become local attachments", () => {
        const messages = recordsToMessages([
            record({
                id: "u1",
                role: "user",
                content: "",
                images: ["abc"],
            }),
        ]);
        expect(messages[0]!.attachments).toEqual([
            {
                kind: "image",
                uri: "data:image/png;base64,abc",
                name: "image-1",
            },
        ]);
    });

    test("an assistant turn keeps reasoning, text and tool calls", () => {
        const messages = recordsToMessages([
            record({
                id: "a1",
                role: "assistant",
                reasoning_content: "think",
                reasoning_elapsed_ms: 1500,
                content: "answer",
                tool_calls: [
                    { id: "t1", name: "read", arguments: '{"path":"a"}' },
                ],
            }),
        ]);
        expect(messages[0]!.parts).toEqual([
            {
                type: "reasoning",
                text: "think",
                elapsedMs: 1500,
                completed: true,
            },
            { type: "text", text: "answer" },
            {
                type: "tool-call",
                toolCallId: "t1",
                toolName: "read",
                inputText: '{"path":"a"}',
                outputText: "",
                status: "done",
            },
        ]);
    });

    test("a tool record fills the matching part", () => {
        const messages = recordsToMessages([
            record({
                id: "a1",
                role: "assistant",
                tool_calls: [
                    { id: "t1", name: "read", arguments: "{}" },
                ],
            }),
            record({
                id: "t1",
                role: "tool",
                tool_call_id: "t1",
                content: '{"content":"hello"}',
            }),
        ]);
        const part = messages[0]!.parts[0];
        expect(part).toMatchObject({
            type: "tool-call",
            toolCallId: "t1",
            status: "done",
        });
        if (part?.type === "tool-call") {
            expect(part.outputText).toContain("hello");
        }
    });

    test("a failed tool record marks the part", () => {
        const messages = recordsToMessages([
            record({
                id: "a1",
                role: "assistant",
                tool_calls: [{ id: "t1", name: "shell", arguments: "{}" }],
            }),
            record({
                id: "t1",
                role: "tool",
                tool_call_id: "t1",
                content: "denied",
                error: "permission denied",
            }),
        ]);
        expect(messages[0]!.parts[0]).toMatchObject({
            type: "tool-call",
            status: "error",
            error: "permission denied",
        });
    });

    test("group_id merges assistant rows into one message", () => {
        const messages = recordsToMessages([
            record({
                id: "a1",
                role: "assistant",
                group_id: "g1",
                content: "first",
            }),
            record({
                id: "a2",
                role: "assistant",
                group_id: "g1",
                content: "second",
            }),
        ]);
        expect(messages).toHaveLength(1);
        expect(messages[0]!.parts).toEqual([
            { type: "text", text: "first" },
            { type: "text", text: "second" },
        ]);
    });
});
