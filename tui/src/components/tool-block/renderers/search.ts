import { backtick, plural, RESULT_LIMITS, cleanLines } from "../format/text.ts";
import type { RenderCtx, ResultView, ToolRenderer } from "../types.ts";

type SearchArgs = {
    pattern?: string;
    query?: string;
    path?: string;
    include?: string;
};

type Parsed = {
    /** Count the tool declared in its header, or null when the header is absent. */
    count: number | null;
    /** Header line and trailing note removed; what the user actually reads. */
    body: string[];
};

const GLOB_HEADER = /^Found (\d+) files\b/;
const GREP_HEADER = /^Found (\d+) matches\b/;
const NOTE = /^[….]{1,2} .*(not shown|truncated)/i;
const GLOB_EMPTY = /^No files found$/i;
const GREP_EMPTY = /^No matches found$/i;

function parseArgs(raw: Record<string, unknown> | null): SearchArgs | null {
    if (raw === null) return {};
    return raw;
}

function subject(args: SearchArgs): string {
    if (typeof args.pattern === "string" && args.pattern.trim()) {
        return args.pattern.trim();
    }
    if (typeof args.query === "string" && args.query.trim()) {
        return args.query.trim();
    }
    return "";
}

function scope(args: SearchArgs): string {
    const path = typeof args.path === "string" ? args.path.trim() : "";
    const include = typeof args.include === "string" ? args.include.trim() : "";
    if (path && include) return `${path} (${include})`;
    return path || include;
}

/**
 * Split a result into its declared count and the lines worth showing.
 *
 * Args:
 *   outputText: Tool output, already sanitised by `ToolBlock`.
 *   header: The `Found N …` line the tool prints on success.
 *   empty: The line the tool prints when it found nothing.
 *
 * Returns:
 *   `count` is null when the header is missing (still running, an error body,
 *   or an unexpected format), so callers can fall back instead of claiming 0.
 */
function parse(outputText: string, header: RegExp, empty: RegExp): Parsed {
    const lines = cleanLines(outputText);
    if (lines.length === 0) return { count: null, body: [] };
    // The tools answer "No files found" / "No matches found" without a header.
    if (empty.test(lines[0]!)) return { count: 0, body: [] };
    const match = header.exec(lines[0]!);
    if (!match) return { count: null, body: lines };
    return {
        count: Number(match[1]),
        body: lines
            .slice(1)
            .filter((line) => line.trim().length > 0 && !NOTE.test(line)),
    };
}

function truncatedNote(outputText: string): string | null {
    for (const line of cleanLines(outputText)) {
        if (NOTE.test(line)) return line.trim();
    }
    return null;
}

/** `C:\dir\a b.ts:12: text`, `src/x.ts:4-9:` — the path may contain colons. */
const MATCH_LINE = /^(.*):(\d+)(?:-(\d+))?:(?:\s|$)/;

function matchedFiles(body: readonly string[]): string[] {
    const files: string[] = [];
    for (const line of body) {
        const match = MATCH_LINE.exec(line);
        if (!match) continue;
        const path = match[1]!;
        if (files.at(-1) !== path && !files.includes(path)) files.push(path);
    }
    return files;
}

function linesResult(lines: string[], limit: number): ResultView {
    return { kind: "lines", lines, hiddenAt: "bottom", limit };
}

/** A running tool with nothing to show yet reports nothing at all. */
function pending(ctx: RenderCtx<SearchArgs>): boolean {
    return ctx.status === "running" && ctx.outputText.trim().length === 0;
}

export const globRenderer: ToolRenderer<SearchArgs> = {
    parseArgs,
    verbs: { running: "Searching for", done: "Searched for", error: "Failed to search" },
    subject,
    meta: (ctx) => {
        if (pending(ctx)) return undefined;
        const { count } = parse(ctx.outputText, GLOB_HEADER, GLOB_EMPTY);
        if (count === null) {
            const lines = cleanLines(ctx.outputText);
            return lines.length > 0 ? `${lines.length} lines` : undefined;
        }
        return `${count} ${plural(count, "file")}`;
    },
    result: (ctx) => {
        if (pending(ctx)) return { kind: "none" };
        const { count, body } = parse(ctx.outputText, GLOB_HEADER, GLOB_EMPTY);
        const note = truncatedNote(ctx.outputText);
        const withNote = note ? [...body, note] : body;
        if (count === null) {
            // Not the shape we expect: show it verbatim rather than inventing 0.
            return body.length > 0
                ? linesResult(withNote, RESULT_LIMITS.list)
                : { kind: "none" };
        }
        if (count === 0) {
            return linesResult(["No files found"], RESULT_LIMITS.list);
        }
        return linesResult(withNote, RESULT_LIMITS.list);
    },
    blockedTitle: (args) => {
        const where = scope(args);
        const target = where ? `${subject(args)} in ${where}` : subject(args);
        return `Waiting for approval — Search ${backtick(target)}`;
    },
};

export const grepRenderer: ToolRenderer<SearchArgs> = {
    parseArgs,
    verbs: { running: "Searching for", done: "Searched for", error: "Failed to search" },
    subject,
    meta: (ctx) => {
        if (pending(ctx)) return undefined;
        const { count, body } = parse(ctx.outputText, GREP_HEADER, GREP_EMPTY);
        if (count === null) {
            const lines = cleanLines(ctx.outputText);
            return lines.length > 0 ? `${lines.length} lines` : undefined;
        }
        const files = matchedFiles(body).length;
        const head = `${count} ${plural(count, "match", "matches")}`;
        return files > 0 ? `${head} in ${files} ${plural(files, "file")}` : head;
    },
    result: (ctx) => {
        if (pending(ctx)) return { kind: "none" };
        const { count, body } = parse(ctx.outputText, GREP_HEADER, GREP_EMPTY);
        const note = truncatedNote(ctx.outputText);
        const withNote = note ? [...body, note] : body;
        if (count === null) {
            return body.length > 0
                ? linesResult(withNote, RESULT_LIMITS.list)
                : { kind: "none" };
        }
        if (count === 0) {
            return linesResult(["No matches"], RESULT_LIMITS.list);
        }
        return linesResult(withNote, RESULT_LIMITS.list);
    },
    blockedTitle: (args) => {
        const where = scope(args);
        const target = where ? `${subject(args)} in ${where}` : subject(args);
        return `Waiting for approval — Search ${backtick(target)}`;
    },
};
