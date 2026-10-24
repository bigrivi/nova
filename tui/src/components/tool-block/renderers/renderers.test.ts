import { describe, expect, test } from "bun:test";
import { getRenderer } from "../registry.ts";

describe("tool renderers", () => {
    test("shell has verbs and subject", () => {
        const renderer = getRenderer("shell");
        const args = renderer.parseArgs({ command: "npm test" });
        expect(args).not.toBeNull();
        expect(renderer.verbs.done).toBe("Ran");
        expect(renderer.subject(args!)).toBe("npm test");
    });

    test("unknown tool falls back", () => {
        const renderer = getRenderer("definitely_unknown");
        expect(renderer.parseArgs({ foo: "bar" })).toEqual({ foo: "bar" });
        expect(renderer.verbs.running).toBe("Running");
    });

    test("read meta reports lines", () => {
        const renderer = getRenderer("read");
        const args = renderer.parseArgs({ filePath: "x.ts" });
        const ctx = {
            part: {} as any,
            args: args!,
            status: "done" as const,
            outputText: "     1\tfoo\n     2\tbar\n",
            width: 80,
            expanded: false,
        };
        expect(renderer.meta?.(ctx)).toBe("2 lines");
    });

    test("todo renderer uses ascii icons", () => {
        const renderer = getRenderer("todo_write");
        const args = renderer.parseArgs({
            todos: [
                { content: "done task", status: "completed" },
                { content: "running task", status: "in_progress" },
                { content: "pending task", status: "pending" },
                { content: "cancelled task", status: "cancelled" },
            ],
        });
        const ctx = {
            part: {} as any,
            args: args!,
            status: "done" as const,
            outputText: "",
            width: 80,
            expanded: false,
        };
        const result = renderer.result?.(ctx);
        expect(result?.kind).toBe("lines");
        if (result?.kind === "lines") {
            expect(result.lines).toEqual([
                "[x] done task",
                "[>] running task",
                "[ ] pending task",
                "[-] cancelled task",
            ]);
        }
        expect(renderer.meta?.(ctx)).toBe("1/4");
    });

    test("grep reports no matches", () => {
        const renderer = getRenderer("grep");
        const args = renderer.parseArgs({ pattern: "nope" });
        const ctx = {
            part: {} as any,
            args: args!,
            status: "done" as const,
            outputText: "No matches found",
            width: 80,
            expanded: false,
        };
        const result = renderer.result?.(ctx);
        expect(result?.kind).toBe("lines");
        if (result?.kind === "lines") {
            expect(result.lines).toEqual(["No matches"]);
        }
    });

    test("error verbs are not the done verb", () => {
        const renderer = getRenderer("read");
        expect(renderer.verbs.error).toBe("Failed to read");
        expect(renderer.verbs.done).toBe("Read");
    });
});