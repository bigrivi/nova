import { describe, expect, test } from "bun:test";
import type { NovaMessageRecord } from "../api/types.ts";
import { recordToMessage, stripFileReferences } from "./history.ts";

function userRecord(overrides: Partial<NovaMessageRecord> = {}): NovaMessageRecord {
    return {
        id: "m1",
        session_id: "s1",
        role: "user",
        content: "hello",
        tool_call_id: null,
        tool_calls: [],
        time_created: 0,
        ...overrides,
    };
}

describe("recordToMessage", () => {
    test("keeps the subagent variant", () => {
        const message = recordToMessage(
            userRecord({
                variant: "subagent",
                content: "[subagent:explorer status=done]\nbody",
            }),
        );
        expect(message.variant).toBe("subagent");
    });

    test("omits the variant for a normal user message", () => {
        const message = recordToMessage(userRecord());
        expect(message.variant).toBeUndefined();
    });

    test("hides the Attached file references appended for the model", () => {
        const message = recordToMessage(
            userRecord({
                content: "summarise this\nAttached file: `src/notes.md`",
            }),
        );
        const part = message.parts[0];
        expect(part?.type === "text" && part.text).toBe("summarise this");
    });

    test("keeps a reference the user typed mid-message out of the filter", () => {
        const content = "look at Attached file: `x` then done";
        expect(stripFileReferences(content)).toBe(content);
    });
});
