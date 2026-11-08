import { describe, expect, test } from "bun:test";

import type { ChatMessage } from "../state/chat";
import { transcriptText } from "./transcript";

function message(
    role: "user" | "assistant",
    parts: ChatMessage["parts"],
): ChatMessage {
    return { id: `${role}-${parts.length}`, role, parts, status: "done" };
}

describe("transcript text", () => {
    test("labels speakers and separates turns with a blank line", () => {
        const text = transcriptText([
            message("user", [{ type: "text", text: "hello" }]),
            message("assistant", [{ type: "text", text: "hi" }]),
        ]);
        expect(text).toBe("You:\nhello\n\nNova:\nhi");
    });

    test("ignores reasoning and tool parts", () => {
        const text = transcriptText([
            message("assistant", [
                { type: "reasoning", text: "think", elapsedMs: null, completed: true },
                { type: "text", text: "answer" },
                {
                    type: "tool-call",
                    toolCallId: "c1",
                    toolName: "shell",
                    inputText: "{}",
                    outputText: "ok",
                    status: "done",
                },
            ]),
        ]);
        expect(text).toBe("Nova:\nanswer");
    });

    test("skips messages without text", () => {
        const text = transcriptText([
            message("user", [{ type: "text", text: "   " }]),
            message("assistant", [{ type: "text", text: "only" }]),
        ]);
        expect(text).toBe("Nova:\nonly");
        expect(transcriptText([])).toBe("");
    });
});
