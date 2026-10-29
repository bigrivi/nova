import { describe, expect, test } from "bun:test";
import type { NovaMemory } from "../api/types.ts";
import { arrangeMemories, memoryDetailLines, memoryLine } from "./memory-format.ts";

function memory(overrides: Partial<NovaMemory> = {}): NovaMemory {
    return {
        id: "m1",
        key: "indent",
        scope: "user",
        memory_type: "preference",
        summary: "I prefer tabs",
        content: "Always indent with tabs.",
        tags: ["style"],
        session_id: null,
        created_at: 1,
        updated_at: 1,
        ...overrides,
    };
}

describe("memoryLine", () => {
    test("leads with the memory type", () => {
        expect(memoryLine(memory())).toContain("preference");
        expect(memoryLine(memory())).toContain("I prefer tabs");
    });

    test("clips a long summary instead of wrapping the row", () => {
        const long = memory({ summary: "x".repeat(200) });
        expect(memoryLine(long).length).toBeLessThan(90);
        expect(memoryLine(long)).toContain("…");
    });

    test("falls back to content when there is no summary", () => {
        expect(memoryLine(memory({ summary: "" }))).toContain("tabs");
    });
});

describe("arrangeMemories", () => {
    test("groups by scope, biggest scope first", () => {
        const rows = arrangeMemories([
            memory({ id: "a", scope: "session" }),
            memory({ id: "b", scope: "user" }),
            memory({ id: "c", scope: "user" }),
        ]);

        expect(rows.map((row) => row.id)).toEqual(["b", "c", "a"]);
        expect(rows[0]?.group).toBe("user (2)");
        expect(rows[2]?.group).toBe("session (1)");
    });

    test("keeps rows contiguous per scope", () => {
        const rows = arrangeMemories([
            memory({ id: "a", scope: "user" }),
            memory({ id: "b", scope: "session" }),
            memory({ id: "c", scope: "user" }),
        ]);

        const scopes = rows.map((row) => row.group);
        expect(scopes).toEqual(["user (2)", "user (2)", "session (1)"]);
    });

    test("returns nothing for no memories", () => {
        expect(arrangeMemories([])).toEqual([]);
    });
});

describe("memoryDetailLines", () => {
    test("names the scope, type and key, then the body", () => {
        const lines = memoryDetailLines(memory());
        expect(lines[0]).toContain("user");
        expect(lines[0]).toContain("indent");
        expect(lines).toContain("Always indent with tabs.");
        expect(lines.join("\n")).toContain("tags: style");
    });

    test("shows a placeholder for an empty body", () => {
        expect(memoryDetailLines(memory({ content: "", summary: "" }))).toContain(
            "(empty)",
        );
    });
});
