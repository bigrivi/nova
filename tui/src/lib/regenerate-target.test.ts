import { describe, expect, test } from "bun:test";
import type { TuiMessage } from "../stores/chat-store.ts";
import { regenerateTarget } from "./regenerate-target.ts";

function message(
    role: "user" | "assistant",
    id: string,
): TuiMessage {
    return {
        id,
        role,
        parts: [],
        status: "done",
    };
}

describe("regenerateTarget", () => {
    test("replaces the answer that follows the last question", () => {
        const target = regenerateTarget([
            message("user", "u1"),
            message("assistant", "a1"),
        ]);

        expect(target).toEqual({ kind: "replace", messageId: "a1" });
    });

    test("appends when the last thing is a question with no answer", () => {
        const target = regenerateTarget([
            message("user", "u1"),
            message("assistant", "a1"),
            message("user", "u2"),
        ]);

        expect(target).toEqual({ kind: "append" });
    });

    test("has nothing to do without a user message", () => {
        const target = regenerateTarget([message("assistant", "a1")]);

        expect(target.kind).toBe("none");
    });

    test("has nothing to do in an empty transcript", () => {
        expect(regenerateTarget([]).kind).toBe("none");
    });

    test("replaces the last answer, not an earlier one", () => {
        const target = regenerateTarget([
            message("user", "u1"),
            message("assistant", "a1"),
            message("user", "u2"),
            message("assistant", "a2"),
            message("user", "u3"),
            message("assistant", "a3"),
        ]);

        expect(target).toEqual({ kind: "replace", messageId: "a3" });
    });
});
