import { backtick } from "../format/text.ts";
import { diffStat, editArgsDiff, extractDiff } from "../format/diff.ts";
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

function writeDiffText(ctx: RenderCtx<FileArgs>): string {
    return extractDiff(ctx.outputText);
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

export const readImageRenderer: ToolRenderer<FileArgs> = {
    ...readRenderer,
    verbs: { running: "Reading", done: "Read", error: "Failed to read" },
    meta: (ctx) => {
        const lines = readLines(ctx);
        return lines > 0 ? `${lines} lines` : undefined;
    },
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
        const diff = writeDiffText(ctx);
        if (diff) {
            return { kind: "diff", diff, synthesized: false };
        }
        return { kind: "none" };
    },
    blockedTitle: (args) => `Waiting for approval — Write ${backtick(subject(args))}`,
};

export const editRenderer: ToolRenderer<FileArgs> = {
    parseArgs,
    verbs: { running: "Editing", done: "Edited", error: "Failed to edit" },
    subject,
    meta: (ctx) => {
        const diff = ctx.outputText.includes("--- ")
            ? extractDiff(ctx.outputText)
            : editArgsDiff(ctx.args);
        if (!diff) return undefined;
        const stat = diffStat(diff);
        if (stat.added === 0 && stat.removed === 0) return undefined;
        return `+${stat.added} -${stat.removed}`;
    },
    result: (ctx) => {
        const diff = ctx.outputText.includes("--- ")
            ? extractDiff(ctx.outputText)
            : editArgsDiff(ctx.args);
        if (!diff) return { kind: "none" };
        return {
            kind: "diff",
            diff,
            synthesized: !ctx.outputText.includes("--- "),
        };
    },
    blockedTitle: (args) => `Waiting for approval — Edit ${backtick(subject(args))}`,
};
