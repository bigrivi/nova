import { describe, expect, test } from "bun:test";
import { buildRegistry, getRenderer } from "../registry.ts";
import type { ToolRenderer } from "../types.ts";

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

    test("prototype keys fall back instead of resolving Object members", () => {
        for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
            const renderer = getRenderer(name);
            expect({ name, running: renderer.verbs.running }).toEqual({
                name,
                running: "Running",
            });
        }
    });

    test("the fallback is built once per tool name", () => {
        expect(getRenderer("some_mcp_tool")).toBe(getRenderer("some_mcp_tool"));
    });

    test("read_image comes from the file renderer, not the simple configs", () => {
        const renderer = getRenderer("read_image");
        const args = renderer.parseArgs({ path: "shot.png" });
        const ctx = {
            part: {} as never,
            args: args!,
            status: "done" as const,
            outputText: JSON.stringify({
                images: ["…"],
                text: "Image loaded: shot.png, format: png, size: 234567 bytes",
            }),
            width: 80,
            expanded: false,
        };
        expect(renderer.subject(args!)).toBe("shot.png");
        expect(renderer.meta?.(ctx)).toBe("png · 229 KB");
        expect(renderer.result?.(ctx)?.kind).toBe("none");
    });

    test("read_image meta is dropped when the payload is not readable", () => {
        const renderer = getRenderer("read_image");
        const args = renderer.parseArgs({ path: "shot.png" });
        for (const outputText of ["", "not json", '{"images":[]}']) {
            const ctx = {
                part: {} as never,
                args: args!,
                status: "done" as const,
                outputText,
                width: 80,
                expanded: false,
            };
            expect(renderer.meta?.(ctx)).toBeUndefined();
        }
    });

    test("buildRegistry rejects a duplicate tool name", () => {
        const renderer = getRenderer("shell");
        expect(() =>
            buildRegistry([
                ["shell", renderer as ToolRenderer],
                ["shell", renderer as ToolRenderer],
            ]),
        ).toThrow(/duplicate tool renderer/);
    });

    test("a truncated write diff is reported as truncated", () => {
        const renderer = getRenderer("write");
        const args = renderer.parseArgs({ filePath: "x.ts" });
        const ctx = {
            part: {} as never,
            args: args!,
            status: "done" as const,
            outputText: [
                "File updated — x.ts:",
                "--- a/x.ts",
                "+++ b/x.ts",
                "@@ -1,2 +1,2 @@",
                " one",
                "-two",
                "+TWO",
                "[... 5 more lines ...]",
            ].join("\n"),
            width: 80,
            expanded: false,
        };
        const view = renderer.result?.(ctx);
        expect(view?.kind).toBe("diff");
        if (view?.kind === "diff") {
            expect(view.truncated).toBe(true);
            expect(view.hiddenLines).toBe(5);
            expect(view.diff).toContain("+TWO");
            expect(view.diff).not.toContain("more lines");
        }
    });

    test("a cut edit patch marks its stat as partial", () => {
        const renderer = getRenderer("edit");
        const args = renderer.parseArgs({ filePath: "x.ts" });
        const ctx = {
            part: {} as never,
            args: args!,
            status: "done" as const,
            outputText: [
                "--- a/x.ts",
                "+++ b/x.ts",
                "@@ -1,2 +1,2 @@",
                " one",
                "-two",
                "+TWO",
                "[... 3 more lines ...]",
            ].join("\n"),
            width: 80,
            expanded: false,
        };
        expect(renderer.meta?.(ctx)).toBe("+1+ -1");
    });
});
