import { backtick, RESULT_LIMITS, cleanLines } from "../format/text.ts";
import type { ToolRenderer } from "../types.ts";

type SearchArgs = { pattern?: string; query?: string; path?: string; include?: string };

function parseArgs(raw: Record<string, unknown> | null): SearchArgs | null {
    if (raw === null) return {};
    return raw;
}

function subject(args: SearchArgs): string {
    if (typeof args.pattern === "string" && args.pattern.trim()) return args.pattern.trim();
    if (typeof args.query === "string" && args.query.trim()) return args.query.trim();
    return "";
}

function globCount(outputText: string): number {
    const match = outputText.match(/^Found (\d+) files:/m);
    return match ? Number(match[1]) : 0;
}

function grepCount(outputText: string): number {
    const match = outputText.match(/^Found (\d+) matches:/m);
    return match ? Number(match[1]) : 0;
}

function grepFiles(outputText: string): number {
    const files = new Set<string>();
    for (const line of outputText.split("\n")) {
        const match = line.match(/^([^:\s]+):\d+:/);
        if (match) files.add(match[1]!);
    }
    return files.size;
}

export const globRenderer: ToolRenderer<SearchArgs> = {
    parseArgs,
    verbs: { running: "Searching for", done: "Searched for", error: "Failed to search" },
    subject,
    meta: (ctx) => {
        const count = globCount(ctx.outputText);
        return `${count} ${count === 1 ? "file" : "files"}`;
    },
    result: (ctx) => {
        const lines = cleanLines(ctx.outputText);
        const count = globCount(ctx.outputText);
        if (count === 0) {
            return { kind: "lines", lines: ["No files found"], hidden: 0, hiddenAt: "bottom", limit: RESULT_LIMITS.list };
        }
        const paths = lines.slice(1).filter((line) => line.trim().length > 0);
        if (paths.length <= RESULT_LIMITS.list) {
            return { kind: "lines", lines: paths, hidden: 0, hiddenAt: "bottom", limit: RESULT_LIMITS.list };
        }
        return {
            kind: "lines",
            lines: paths.slice(0, RESULT_LIMITS.list),
            hidden: paths.length - RESULT_LIMITS.list,
            hiddenAt: "bottom",
            limit: RESULT_LIMITS.list,
        };
    },
    blockedTitle: (args) => `Waiting for approval — Search ${backtick(subject(args))}`,
};

export const grepRenderer: ToolRenderer<SearchArgs> = {
    parseArgs,
    verbs: { running: "Searching for", done: "Searched for", error: "Failed to search" },
    subject,
    meta: (ctx) => {
        const matches = grepCount(ctx.outputText);
        const files = grepFiles(ctx.outputText);
        return files > 0
            ? `${matches} ${matches === 1 ? "match" : "matches"} in ${files} ${files === 1 ? "file" : "files"}`
            : `${matches} ${matches === 1 ? "match" : "matches"}`;
    },
    result: (ctx) => {
        const lines = cleanLines(ctx.outputText);
        const matches = grepCount(ctx.outputText);
        if (matches === 0) {
            return { kind: "lines", lines: ["No matches"], hidden: 0, hiddenAt: "bottom", limit: RESULT_LIMITS.list };
        }
        // Keep the "Found N matches:" header out of the rendered lines.
        const body = lines.slice(1).filter((line) => line.trim().length > 0);
        if (body.length <= RESULT_LIMITS.list) {
            return { kind: "lines", lines: body, hidden: 0, hiddenAt: "bottom", limit: RESULT_LIMITS.list };
        }
        return {
            kind: "lines",
            lines: body.slice(0, RESULT_LIMITS.list),
            hidden: body.length - RESULT_LIMITS.list,
            hiddenAt: "bottom",
            limit: RESULT_LIMITS.list,
        };
    },
    blockedTitle: (args) => `Waiting for approval — Search ${backtick(subject(args))}`,
};
