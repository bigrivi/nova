import { describe, expect, test } from "bun:test";
import {
    EXPLORATION_TOOLS,
    explorationCompleted,
    explorationLabel,
    groupAssistantParts,
} from "./group-parts.ts";

describe("groupAssistantParts", () => {
    test("merges adjacent exploration tools", () => {
        const parts = [
            { type: "tool-call", toolCallId: "a", toolName: "grep", args: null, argsText: "", outputText: "", status: "done" },
            { type: "tool-call", toolCallId: "b", toolName: "read", args: null, argsText: "", outputText: "", status: "done" },
        ] as any;
        const items = groupAssistantParts("m", parts);
        expect(items).toHaveLength(1);
        expect(items[0]!.kind).toBe("explore");
        if (items[0]!.kind === "explore") {
            expect(items[0]!.parts.map((p) => p.toolName)).toEqual(["grep", "read"]);
            expect(explorationLabel(items[0]!.parts, explorationCompleted(items[0]!.parts))).toBe("Explored: 1 search, 1 read");
        }
    });

    test("breaks on reasoning", () => {
        const parts = [
            { type: "tool-call", toolCallId: "a", toolName: "read", args: null, argsText: "", outputText: "", status: "done" },
            { type: "reasoning", text: "x", elapsedMs: null, completed: true },
            { type: "tool-call", toolCallId: "b", toolName: "read", args: null, argsText: "", outputText: "", status: "running" },
        ] as any;
        const items = groupAssistantParts("m", parts);
        expect(items).toHaveLength(3);
        expect(items[0]!.kind).toBe("explore");
        expect(items[1]!.kind).toBe("part");
        expect(items[2]!.kind).toBe("explore");
        if (items[2]!.kind === "explore") {
            expect(explorationLabel(items[2]!.parts, explorationCompleted(items[2]!.parts))).toBe("Exploring: 1 read");
        }
    });

    test("shell is not an exploration tool", () => {
        expect(EXPLORATION_TOOLS.has("shell")).toBe(false);
    });
});