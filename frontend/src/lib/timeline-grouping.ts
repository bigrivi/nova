import type { GroupByContext, PartState } from "@assistant-ui/react";

export type TimelineGroupKey =
    | "group-chainOfThought"
    | "group-reasoning"
    | "group-tool"
    | "group-tool-standalone"
    | "group-blank";

const CHAIN_OF_THOUGHT: TimelineGroupKey = "group-chainOfThought";
const GROUP_REASONING: TimelineGroupKey = "group-reasoning";
const GROUP_TOOL: TimelineGroupKey = "group-tool";
const GROUP_TOOL_STANDALONE: TimelineGroupKey = "group-tool-standalone";
const GROUP_BLANK: TimelineGroupKey = "group-blank";

export type TimelinePart = {
    type: string;
    toolName?: string;
    text?: string;
    mcp?: unknown;
};

function hasReplyText(part: TimelinePart): boolean {
    return part.type === "text" && (part.text ?? "").trim() !== "";
}

function isMcpAppToolCall(part: TimelinePart): boolean {
    const mcp = part.mcp;
    if (!mcp || typeof mcp !== "object") {
        return false;
    }
    const app = (mcp as { app?: unknown }).app;
    if (!app || typeof app !== "object") {
        return false;
    }
    const resourceUri = (app as { resourceUri?: unknown }).resourceUri;
    return typeof resourceUri === "string" && resourceUri.startsWith("ui://");
}

export function isStandaloneToolCall(
    part: TimelinePart,
    context?: GroupByContext,
): boolean {
    if (part.type !== "tool-call") {
        return false;
    }
    if (isMcpAppToolCall(part)) {
        return true;
    }
    const name = part.toolName ?? "";
    return Boolean(context?.toolUIs?.[name]?.[0]?.standalone);
}

function classifyPart(
    part: TimelinePart,
    inThinking: boolean,
    context?: GroupByContext,
): TimelineGroupKey[] {
    if (part.type === "reasoning") {
        return inThinking ? [CHAIN_OF_THOUGHT, GROUP_REASONING] : [];
    }

    if (part.type === "text") {
        const blank = (part.text ?? "").trim() === "";
        return blank && inThinking ? [CHAIN_OF_THOUGHT, GROUP_BLANK] : [];
    }

    if (part.type === "tool-call") {
        if (isStandaloneToolCall(part, context)) {
            return [GROUP_TOOL_STANDALONE];
        }
        return inThinking
            ? [CHAIN_OF_THOUGHT, GROUP_TOOL]
            : [GROUP_TOOL_STANDALONE];
    }

    return [];
}

export function findPrimaryChainStart(
    parts: readonly TimelinePart[],
): number {
    return parts.findIndex((part) => part.type === "reasoning");
}

export function readPartElapsedMs(part: unknown): number | null {
    if (part && typeof part === "object" && "elapsedMs" in part) {
        const value = (part as { elapsedMs?: unknown }).elapsedMs;
        if (typeof value === "number") {
            return value;
        }
    }
    return null;
}

export function buildTimelinePaths(
    parts: readonly TimelinePart[],
    context?: GroupByContext,
): TimelineGroupKey[][] {
    const paths: TimelineGroupKey[][] = parts.map(() => []);

    let index = 0;
    while (index < parts.length) {
        if (hasReplyText(parts[index])) {
            index += 1;
            continue;
        }

        let end = index;
        while (end < parts.length && !hasReplyText(parts[end])) {
            end += 1;
        }

        const hasThinkingBlock = parts
            .slice(index, end)
            .some((part) => part.type === "reasoning");

        for (let cursor = index; cursor < end; cursor += 1) {
            paths[cursor] = classifyPart(parts[cursor], hasThinkingBlock, context);
        }

        index = end;
    }

    return paths;
}

export function buildTimelinePathMap(
    parts: readonly TimelinePart[],
    context?: GroupByContext,
): Map<TimelinePart, TimelineGroupKey[]> {
    const paths = buildTimelinePaths(parts, context);
    const pathByPart = new Map<TimelinePart, TimelineGroupKey[]>();
    parts.forEach((part, index) => {
        pathByPart.set(part, paths[index] ?? []);
    });
    return pathByPart;
}

export type TimelineGroupBy = (
    part: PartState,
    context?: GroupByContext,
) => readonly TimelineGroupKey[];

export function createTimelineGroupBy(
    pathByPart: Map<TimelinePart, TimelineGroupKey[]>,
): TimelineGroupBy {
    return (part) => pathByPart.get(part) ?? [];
}
