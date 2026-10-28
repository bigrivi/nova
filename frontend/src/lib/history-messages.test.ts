import { describe, expect, test } from "vitest";

import { toThreadMessages } from "./history-messages";
import type { NovaMessageRecord } from "@/types/nova";

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
    } as NovaMessageRecord;
}

describe("toThreadMessages", () => {
    test("renders the display text instead of the model-facing content", () => {
        const [message] = toThreadMessages([
            userRecord({
                content: "look\nAttached file: `src/notes.md`",
                display_text: "look",
            }),
        ]);
        expect(message?.content).toBe("look");
    });

    test("falls back to content when a row has no display text", () => {
        const [message] = toThreadMessages([userRecord({ content: "hello" })]);
        expect(message?.content).toBe("hello");
    });

    test("keeps images alongside the text", () => {
        const [message] = toThreadMessages([
            userRecord({
                content: "look",
                images: ["data:image/png;base64,QUJD"],
            }),
        ]);
        expect(Array.isArray(message?.content)).toBe(true);
        expect(message?.content).toEqual([
            { type: "image", image: "data:image/png;base64,QUJD" },
            { type: "text", text: "look" },
        ]);
    });
});
