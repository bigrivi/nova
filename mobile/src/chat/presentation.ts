/**
 * Presentation rules shared by the chat transcript and composer.
 *
 * These are the parts of the web UI that are not styling: how a thinking
 * segment becomes one collapsible chain, when a tool call is standalone, how a
 * tool's status folds into running/cancelled/errored, and how the server's
 * synthetic text headers are taken apart. Ported from
 * `frontend/src/lib/timeline-grouping.ts`, `tool-outcome.ts`, and
 * `thread-message.tsx`.
 *
 * Pure functions only: the React Native components own layout and animation.
 */

export type TimelinePart = {
    type: string;
    text?: string;
    toolName?: string;
    elapsedMs?: number | null;
    mcp?: { app?: { resourceUri?: string } } | null;
    /** Set by the caller when a tool renders as its own card. */
    standalone?: boolean;
};

export type TimelineItem =
    | { kind: "text"; index: number }
    | { kind: "tool"; index: number }
    | {
          kind: "chain";
          indices: number[];
          toolCount: number;
          elapsedMs: number | null;
      };

/** Rendered by their own components, never as a timeline row. */
export const HIDDEN_TOOL_NAMES: ReadonlySet<string> = new Set([
    "ask_user",
    "todo_write",
]);

function isReplyText(part: TimelinePart): boolean {
    return part.type === "text" && (part.text ?? "").trim() !== "";
}

function isHiddenTool(part: TimelinePart): boolean {
    return part.type === "tool-call" && HIDDEN_TOOL_NAMES.has(part.toolName ?? "");
}

function isMcpAppToolCall(part: TimelinePart): boolean {
    const resourceUri = part.mcp?.app?.resourceUri;
    return typeof resourceUri === "string" && resourceUri.startsWith("ui://");
}

export function isStandaloneToolCall(part: TimelinePart): boolean {
    return (
        part.type === "tool-call" &&
        (isMcpAppToolCall(part) || part.standalone === true)
    );
}

export function readPartElapsedMs(part: TimelinePart): number | null {
    return typeof part.elapsedMs === "number" ? part.elapsedMs : null;
}

export function chainStats(
    parts: readonly TimelinePart[],
    indices: readonly number[],
): { toolCount: number; elapsedMs: number | null } {
    let toolCount = 0;
    let elapsed = 0;
    let hasElapsed = false;
    for (const index of indices) {
        const part = parts[index];
        if (!part) {
            continue;
        }
        if (part.type === "tool-call" && !isHiddenTool(part)) {
            toolCount += 1;
        }
        if (part.type === "reasoning") {
            const value = readPartElapsedMs(part);
            if (value !== null) {
                elapsed += value;
                hasElapsed = true;
            }
        }
    }
    return { toolCount, elapsedMs: hasElapsed ? elapsed : null };
}

/**
 * Turn a message's parts into what the phone actually renders.
 *
 * Web behaviour, restated so it can be tested without assistant-ui:
 * - a reply text part is its own row;
 * - between two reply texts, reasoning plus non-standalone tools collapse into
 *   one thinking chain, even when tools interleave with reasoning;
 * - a standalone tool (MCP app UI, or one a tool UI marks standalone) breaks
 *   the chain and becomes its own card;
 * - `ask_user` and `todo_write` are hidden here because their own UI renders
 *   them;
 * - blank text and unknown part types are visual joiners, not rows.
 */
export function buildTimelineItems(
    parts: readonly TimelinePart[],
): TimelineItem[] {
    const items: TimelineItem[] = [];
    let index = 0;

    while (index < parts.length) {
        const part = parts[index]!;
        if (isReplyText(part)) {
            items.push({ kind: "text", index });
            index += 1;
            continue;
        }

        let end = index;
        while (end < parts.length && !isReplyText(parts[end]!)) {
            end += 1;
        }

        const hasThinking = parts
            .slice(index, end)
            .some((candidate) => candidate.type === "reasoning");

        if (!hasThinking) {
            for (let cursor = index; cursor < end; cursor += 1) {
                const candidate = parts[cursor]!;
                if (candidate.type === "tool-call" && !isHiddenTool(candidate)) {
                    items.push({ kind: "tool", index: cursor });
                }
            }
            index = end;
            continue;
        }

        let chain: number[] = [];
        const flush = () => {
            if (chain.length === 0) {
                return;
            }
            items.push({
                kind: "chain",
                indices: chain,
                ...chainStats(parts, chain),
            });
            chain = [];
        };

        for (let cursor = index; cursor < end; cursor += 1) {
            const candidate = parts[cursor]!;
            if (candidate.type === "reasoning") {
                chain.push(cursor);
                continue;
            }
            if (candidate.type === "tool-call") {
                if (isHiddenTool(candidate)) {
                    continue;
                }
                if (isStandaloneToolCall(candidate)) {
                    flush();
                    items.push({ kind: "tool", index: cursor });
                } else {
                    chain.push(cursor);
                }
            }
        }
        flush();
        index = end;
    }

    return items;
}

/** `[(tool)]` summary for a collapsed tool row, as the web computes it. */
const PARAM_CANDIDATES = [
    "filePath",
    "path",
    "file",
    "pattern",
    "query",
    "command",
    "url",
    "glob",
    "prompt",
] as const;

export function toolParamSummary(argsText?: string): string | null {
    if (!argsText) {
        return null;
    }
    const trimmed = argsText.trim();
    if (!trimmed) {
        return null;
    }
    try {
        const parsed: unknown = JSON.parse(trimmed);
        if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
            const record = parsed as Record<string, unknown>;
            for (const key of PARAM_CANDIDATES) {
                const value = record[key];
                if (typeof value === "string" && value.trim()) {
                    return value.trim();
                }
            }
            for (const value of Object.values(record)) {
                if (typeof value === "string" && value.trim()) {
                    return value.trim();
                }
            }
            return trimmed;
        }
    } catch {
        return trimmed;
    }
    return trimmed;
}

export type ParsedAttachment = { name: string; text: string };

/** `<attachment name=...>` blocks the server folds into a user message. */
export function parseAttachment(text: string): ParsedAttachment | null {
    const match = text.match(
        /^<attachment name=(.*?)>\n([\s\S]*?)\n<\/attachment>\n\n([\s\S]*)$/,
    );
    if (!match) {
        return null;
    }
    return { name: match[1]!, text: match[3]! };
}

export type ParsedSubagent = {
    target: string;
    status: "done" | "error";
    body: string;
};

/**
 * Read back the header the backend wrote into a sub-agent report.
 *
 * Whether a message *is* a report is decided by the server-set variant, not by
 * this shape; a user may paste something that looks identical.
 */
export function parseSubagentMessage(text: string): ParsedSubagent | null {
    const match = text.match(
        /^\[subagent:(.+?)\s+status=(done|error)\]\s*\n?([\s\S]*)$/,
    );
    if (!match) {
        return null;
    }
    const target = match[1]!.trim();
    if (!target) {
        return null;
    }
    return {
        target,
        status: match[2] === "error" ? "error" : "done",
        body: match[3]!.replace(/^\n+/, ""),
    };
}

/** 49.5K / 1.2M, the compact counts used by the context ring. */
export function formatTokenCount(value: number): string {
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}M`;
    }
    if (value >= 1_000) {
        return `${(value / 1_000).toFixed(1)}K`;
    }
    return String(Math.max(0, Math.round(value)));
}

export function contextRingRatio(used: number, limit: number): number {
    return limit > 0 ? Math.min(1, Math.max(0, used / limit)) : 0;
}

export const CONTEXT_WARN_PERCENT = 85;

export function contextRingWarns(percent: number): boolean {
    return percent >= CONTEXT_WARN_PERCENT;
}

/** 850ms / 1.2s / 1m 5s, matching the reasoning header. */
export function formatDuration(ms: number): string {
    if (ms < 1000) {
        return `${ms}ms`;
    }
    if (ms < 60_000) {
        return `${(ms / 1000).toFixed(1)}s`;
    }
    const minutes = Math.floor(ms / 60_000);
    const seconds = Math.floor((ms % 60_000) / 1000);
    return `${minutes}m ${seconds}s`;
}
