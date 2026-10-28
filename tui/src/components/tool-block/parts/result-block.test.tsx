import { expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../../../test-utils/mocked-theme.ts";

mock.module("../../../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { ResultBlock } = await import("./ResultBlock.tsx");
const { getRenderer } = await import("../registry.ts");
const { RESULT_LIMITS } = await import("../format/text.ts");

async function render(view: Parameters<typeof ResultBlock>[0]["view"], expanded = false) {
    const setup = await testRender(
        <ResultBlock view={view} expanded={expanded} />,
        { width: 80, height: 40 },
    );
    await setup.flush();
    return setup.captureCharFrame().split("\n").filter((line) => line.trim().length > 0);
}

const many = (n: number) => Array.from({ length: n }, (_, index) => `line ${index}`);

test("twenty lines fold to three plus a counted hint", async () => {
    const lines = await render({
        kind: "lines",
        lines: many(20),
        hiddenAt: "bottom",
        limit: 3,
    });
    expect(lines.filter((line) => line.includes("line "))).toHaveLength(3);
    expect(lines.at(-1)).toContain("+17 lines");
    expect(lines.at(-1)).toContain("ctrl+o to expand");
});

test("expanding shows every line and stops advertising the key", async () => {
    const lines = await render(
        { kind: "lines", lines: many(20), hiddenAt: "bottom", limit: 3 },
        true,
    );
    expect(lines.filter((line) => line.includes("line "))).toHaveLength(20);
    expect(lines.join("\n")).not.toContain("ctrl+o");
});

test("a top fold keeps the tail and puts the hint first", async () => {
    const lines = await render({
        kind: "lines",
        lines: many(20),
        hiddenAt: "top",
        limit: 3,
    });
    expect(lines[0]).toContain("+17 lines");
    expect(lines.join("\n")).toContain("line 19");
    expect(lines.join("\n")).not.toContain("line 0\n");
});

test("a single hidden line is singular", async () => {
    const lines = await render({
        kind: "lines",
        lines: many(4),
        hiddenAt: "bottom",
        limit: 3,
    });
    expect(lines.at(-1)).toContain("+1 line ");
});

test("blank lines never reach the gutter", async () => {
    const lines = await render({
        kind: "lines",
        lines: ["a", "", "  ", "b"],
        hiddenAt: "bottom",
    });
    expect(lines.join("\n")).not.toMatch(/└\s*$/m);
});

test("renderers hand over complete output so the fold can count", async () => {
    const shell = getRenderer("shell");
    const ctx = {
        part: {} as never,
        args: { command: "ls" },
        status: "done" as const,
        outputText: many(25).join("\n"),
        width: 80,
        expanded: false,
    };
    const view = shell.result?.(ctx);
    expect(view?.kind).toBe("lines");
    if (view?.kind === "lines") {
        expect(view.lines).toHaveLength(25);
        expect(view.limit).toBe(RESULT_LIMITS.shellOk);
    }

    for (const [name, output] of [
        ["glob", `Found 2 files:\na.ts\nb.ts`],
        ["grep", `Found 2 matches:\na.ts:1: x\na.ts:2: y`],
        ["todo_write", ""],
        ["web_search", "line\nline\nline\nline"],
        ["some_mcp_tool", "a\nb\nc\nd"],
    ] as const) {
        const renderer = getRenderer(name);
        const args = renderer.parseArgs(name === "todo_write" ? { todos: [] } : {});
        const result = renderer.result?.({
            ...ctx,
            args: args ?? {},
            outputText: output,
            status: name === "some_mcp_tool" ? "running" : "done",
        });
        if (result?.kind === "lines") {
            expect({ name, complete: result.lines.length < RESULT_LIMITS.expandedMax })
                .toMatchObject({ name, complete: true });
        }
    }
});
