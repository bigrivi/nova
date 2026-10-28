import { backtick } from "../format/text.ts";
import { diffStat, editArgsDiff, parseToolDiff } from "../format/diff.ts";
import type { RenderCtx, ToolRenderer } from "../types.ts";

type FileArgs = {
    filePath?: string;
    path?: string;
    oldString?: string;
    newString?: string;
    offset?: number;
    limit?: number;
    content?: string;
};

function parseArgs(raw: Record<string, unknown> | null): FileArgs | null {
    if (raw === null) return {};
    return raw;
}

function filePath(args: FileArgs): string {
    if (typeof args.filePath === "string" && args.filePath.trim()) return args.filePath.trim();
    if (typeof args.path === "string" && args.path.trim()) return args.path.trim();
    return "";
}

function subject(args: FileArgs): string {
    return filePath(args) || "file";
}

function readLines(ctx: RenderCtx<FileArgs>): number {
    if (ctx.outputText.trim() === "(empty file)") return 0;
    const lines = ctx.outputText.split("\n");
    while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
    return lines.length;
}

function readRange(args: FileArgs): string | undefined {
    const start = typeof args.offset === "number" ? args.offset : 1;
    const limit = typeof args.limit === "number" ? args.limit : undefined;
    if (limit === undefined) return undefined;
    return `L${start}–${start + limit - 1}`;
}

function contentLines(args: FileArgs): number | undefined {
    if (typeof args.content !== "string") return undefined;
    const lines = args.content.split("\n");
    if (args.content === "") return 0;
    return args.content.endsWith("\n") ? lines.length - 1 : lines.length;
}

function writeDiff(ctx: RenderCtx<FileArgs>) {
    return parseToolDiff(ctx.outputText);
}

export const readRenderer: ToolRenderer<FileArgs> = {
    parseArgs,
    verbs: { running: "Reading", done: "Read", error: "Failed to read" },
    subject,
    meta: (ctx) => {
        const range = readRange(ctx.args);
        if (range) return range;
        const lines = readLines(ctx);
        return lines > 0 ? `${lines} lines` : undefined;
    },
    result: () => ({ kind: "none" }),
    blockedTitle: (args) => `Waiting for approval — Read ${backtick(subject(args))}`,
};

/** `format` and `size` from the tool's JSON payload, when it is parseable. */
function imageMeta(ctx: RenderCtx<FileArgs>): string | undefined {
    if (!ctx.outputText.trimStart().startsWith("{")) return undefined;
    let text = "";
    try {
        const payload = JSON.parse(ctx.outputText) as { text?: unknown };
        text = typeof payload.text === "string" ? payload.text : "";
    } catch {
        // Not JSON: a streamed or truncated payload has no meta to show.
        return undefined;
    }
    const format = /format: ([^,\s]+)/.exec(text)?.[1];
    const bytes = Number(/size: (\d+) bytes/.exec(text)?.[1] ?? Number.NaN);
    const size = Number.isFinite(bytes)
        ? `${Math.max(1, Math.round(bytes / 1024))} KB`
        : undefined;
    const parts = [format, size].filter((part): part is string => Boolean(part));
    return parts.length > 0 ? parts.join(" · ") : undefined;
}

export const readImageRenderer: ToolRenderer<FileArgs> = {
    ...readRenderer,
    verbs: { running: "Reading", done: "Read", error: "Failed to read" },
    meta: imageMeta,
    result: () => ({ kind: "none" }),
};

export const writeRenderer: ToolRenderer<FileArgs> = {
    parseArgs,
    verbs: { running: "Writing", done: "Wrote", error: "Failed to write" },
    subject,
    meta: (ctx) => {
        const lines = contentLines(ctx.args);
        return lines !== undefined ? `${lines} lines` : undefined;
    },
    result: (ctx) => {
        const parsed = writeDiff(ctx);
        if (!parsed.diff) return { kind: "none" };
        return {
            kind: "diff",
            diff: parsed.diff,
            synthesized: false,
            truncated: parsed.truncated,
            hiddenLines: parsed.hiddenLines,
        };
    },
    blockedTitle: (args) => `Waiting for approval — Write ${backtick(subject(args))}`,
};

export const editRenderer: ToolRenderer<FileArgs> = {
    parseArgs,
    verbs: { running: "Editing", done: "Edited", error: "Failed to edit" },
    subject,
    meta: (ctx) => {
        const parsed = ctx.outputText.includes("--- ")
            ? parseToolDiff(ctx.outputText)
            : { diff: editArgsDiff(ctx.args), truncated: false };
        if (!parsed.diff) return undefined;
        const stat = diffStat(parsed.diff);
        if (stat.added === 0 && stat.removed === 0) return undefined;
        // A cut patch undercounts, so say so rather than implying a total.
        const suffix = parsed.truncated ? "+" : "";
        return `+${stat.added}${suffix} -${stat.removed}`;
    },
    result: (ctx) => {
        const parsed = ctx.outputText.includes("--- ")
            ? parseToolDiff(ctx.outputText)
            : { diff: editArgsDiff(ctx.args), truncated: false };
        if (!parsed.diff) return { kind: "none" };
        return {
            kind: "diff",
            diff: parsed.diff,
            synthesized: ctx.args.oldString !== undefined && !ctx.outputText.includes("--- "),
            truncated: parsed.truncated,
            hiddenLines: parsed.hiddenLines,
        };
    },
    blockedTitle: (args) => `Waiting for approval — Edit ${backtick(subject(args))}`,
};
