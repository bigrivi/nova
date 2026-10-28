import { describe, expect, test } from "bun:test";
import { getRenderer } from "../registry.ts";
import type { RenderCtx } from "../types.ts";

type Ctx = Partial<RenderCtx<unknown>> & { status: RenderCtx<unknown>["status"] };

function ctx({ status, outputText = "", ...rest }: Ctx) {
    return {
        part: {} as never,
        args: {},
        error: undefined,
        width: 80,
        expanded: false,
        ...rest,
        status,
        outputText,
    } as RenderCtx<Record<string, unknown>>;
}

function lines(view: ReturnType<NonNullable<ReturnType<typeof getRenderer>["result"]>>) {
    return view.kind === "lines" ? view.lines : [];
}

describe("glob renderer", () => {
    const glob = getRenderer("glob");

    test("a running search with no output says nothing", () => {
        const pending = ctx({ status: "running" });
        expect(glob.meta?.(pending)).toBeUndefined();
        expect(glob.result?.(pending)?.kind).toBe("none");
    });

    test("a truncated header still yields the declared count", () => {
        const output = [
            "Found 12 files (showing the first 8, most recently modified):",
            "a.ts",
            "b.ts",
            "… 4 more files not shown; narrow the pattern or path.",
        ].join("\n");
        const view = ctx({ status: "done", outputText: output });
        expect(glob.meta?.(view)).toBe("12 files");
        const rendered = lines(glob.result?.(view)!);
        expect(rendered).toContain("a.ts");
        expect(rendered.at(-1)).toContain("4 more files not shown");
    });

    test("an empty result is reported as empty, not as zero lines", () => {
        const view = ctx({ status: "done", outputText: "No files found" });
        expect(glob.meta?.(view)).toBe("0 files");
        expect(lines(glob.result?.(view)!)).toEqual(["No files found"]);
    });

    test("an unexpected format falls back to the raw lines and counts them", () => {
        const view = ctx({ status: "done", outputText: "something odd\nsecond line" });
        expect(glob.meta?.(view)).toBe("2 lines");
        expect(lines(glob.result?.(view)!)).toEqual(["something odd", "second line"]);
    });

    test("an error body never claims zero results", () => {
        const view = ctx({ status: "error", outputText: "boom" });
        expect(glob.meta?.(view)).toBe("1 lines");
    });
});

describe("grep renderer", () => {
    const grep = getRenderer("grep");

    test("a running search with no output says nothing", () => {
        const pending = ctx({ status: "running" });
        expect(grep.meta?.(pending)).toBeUndefined();
        expect(grep.result?.(pending)?.kind).toBe("none");
    });

    test("counts matches and files", () => {
        const output = [
            "Found 3 matches:",
            "src/a.ts:4: one",
            "src/a.ts:9: two",
            "src/b c.ts:12: three",
        ].join("\n");
        const view = ctx({ status: "done", outputText: output });
        expect(grep.meta?.(view)).toBe("3 matches in 2 files");
    });

    test("keeps the path when it contains spaces, colons or a drive letter", () => {
        const output = [
            "Found 3 matches:",
            "C:\\repo\\a b.ts:12: one",
            "src/命名/文件.ts:4-9: two",
            "src/x.ts:1: three",
        ].join("\n");
        const view = ctx({ status: "done", outputText: output });
        expect(grep.meta?.(view)).toBe("3 matches in 3 files");
        expect(lines(grep.result?.(view)!)).toEqual(output.split("\n").slice(1));
    });

    test("a single match uses the singular", () => {
        const view = ctx({
            status: "done",
            outputText: "Found 1 matches:\nsrc/a.ts:4: one",
        });
        expect(grep.meta?.(view)).toBe("1 match in 1 file");
    });

    test("an empty result is reported as empty", () => {
        const view = ctx({ status: "done", outputText: "No matches found" });
        expect(grep.meta?.(view)).toBe("0 matches");
        expect(lines(grep.result?.(view)!)).toEqual(["No matches"]);
    });

    test("a truncated body keeps the note", () => {
        const output = [
            "Found 40 matches:",
            "src/a.ts:4: one",
            "… output truncated; 39 more lines not shown.",
        ].join("\n");
        const view = ctx({ status: "done", outputText: output });
        expect(lines(grep.result?.(view)!).at(-1)).toContain("39 more lines");
    });
});

describe("search subjects", () => {
    test("glob reports the pattern and its scope in the approval prompt", () => {
        const glob = getRenderer("glob");
        const args = glob.parseArgs({ pattern: "*.ts", path: "src", include: "*.ts" });
        expect(glob.blockedTitle?.(args!)).toContain("*.ts in src");
    });
});
