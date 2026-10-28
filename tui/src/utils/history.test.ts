import { describe, expect, test } from "bun:test";
import type { NovaMessageRecord } from "../api/types.ts";
import {
    recordToMessage,
    referencedFileNames,
    stripFileReferences,
} from "./history.ts";

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

    test("a file-only turn replays as a chip, not an empty bubble", () => {
        const message = recordToMessage(
            userRecord({ content: "Attached file: `src/lib/notes.md`" }),
        );
        const part = message.parts[0];
        expect(part?.type === "text" && part.text).toBe("▧ notes.md");
    });

    test("referenced names survive Windows and absolute paths", () => {
        expect(
            referencedFileNames(
                "Attached file: `C:\\repo\\a.md`\nAttached file: `/tmp/b.ts`",
            ),
        ).toEqual(["a.md", "b.ts"]);
    });

    test("prefers the stored display text over the prompt decoration", () => {
        const message = recordToMessage(
            userRecord({
                content: "look\nAttached file: `src/notes.md`",
                display_text: "look",
            }),
        );
        const part = message.parts[0];
        expect(part?.type === "text" && part.text).toBe("look");
    });

    test("falls back to stripping when an old row has no display text", () => {
        const message = recordToMessage(
            userRecord({ content: "look\nAttached file: `a.md`", display_text: null }),
        );
        const part = message.parts[0];
        expect(part?.type === "text" && part.text).toBe("look");
    });
});
