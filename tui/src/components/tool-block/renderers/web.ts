import { backtick, RESULT_LIMITS, cleanLines } from "../format/text.ts";
import type { ToolRenderer } from "../types.ts";

type WebArgs = { query?: string; url?: string };

function parseArgs(raw: Record<string, unknown> | null): WebArgs | null {
    if (raw === null) return {};
    return raw;
}

function querySubject(args: WebArgs): string {
    return typeof args.query === "string" && args.query.trim() ? args.query.trim() : "";
}

function urlSubject(args: WebArgs): string {
    return typeof args.url === "string" && args.url.trim() ? args.url.trim() : "";
}

function domain(url: string): string {
    try {
        return new URL(url).hostname.replace(/^www\./, "");
    } catch {
        return url;
    }
}

export const webSearchRenderer: ToolRenderer<WebArgs> = {
    parseArgs,
    verbs: { running: "Searching the web for", done: "Searched the web for", error: "Failed to search" },
    subject: querySubject,
    meta: (ctx) => {
        try {
            const parsed = JSON.parse(ctx.outputText) as { results?: unknown };
            if (Array.isArray(parsed.results)) {
                const n = parsed.results.length;
                return `${n} ${n === 1 ? "result" : "results"}`;
            }
        } catch {
            // Fall back to a line count below.
        }
        const lines = cleanLines(ctx.outputText);
        return lines.length > 0 ? `${lines.length} lines` : undefined;
    },
    result: (ctx) => {
        try {
            const parsed = JSON.parse(ctx.outputText) as { results?: unknown };
            if (Array.isArray(parsed.results)) {
                const lines = parsed.results
                    .slice(0, 3)
                    .map((item) => {
                        const row = item as { title?: unknown; url?: unknown };
                        const title = typeof row.title === "string" ? row.title : "Untitled";
                        const url = typeof row.url === "string" ? row.url : "";
                        return url ? `${title} — ${domain(url)}` : title;
                    });
                return lines.length > 0
                    ? { kind: "lines", lines, hidden: 0, hiddenAt: "bottom", limit: RESULT_LIMITS.list }
                    : { kind: "none" };
            }
        } catch {
            // Fall back to generic lines.
        }
        const lines = cleanLines(ctx.outputText).slice(0, RESULT_LIMITS.generic);
        return lines.length > 0
            ? { kind: "lines", lines, hidden: 0, hiddenAt: "bottom", limit: RESULT_LIMITS.generic }
            : { kind: "none" };
    },
    blockedTitle: (args) => `Waiting for approval — Search ${backtick(querySubject(args))}`,
};

export const webFetchRenderer: ToolRenderer<WebArgs> = {
    parseArgs,
    verbs: { running: "Fetching", done: "Fetched", error: "Failed to fetch" },
    subject: urlSubject,
    result: (ctx) => {
        const title = ctx.outputText.match(/^#\s+(.+)$/m)?.[1]?.trim();
        return title
            ? { kind: "lines", lines: [title], hidden: 0, hiddenAt: "bottom", limit: 1 }
            : { kind: "none" };
    },
    blockedTitle: (args) => `Waiting for approval — Fetch ${backtick(urlSubject(args))}`,
};
