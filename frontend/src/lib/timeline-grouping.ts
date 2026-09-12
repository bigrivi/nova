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

const HIDDEN_TOOL_NAMES = new Set(["ask_user", "todo_write"]);

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

export function buildTimelinePaths(
    parts: readonly TimelinePart[],
    context?: GroupByContext,
): TimelineGroupKey[][] {
    const replyIndex = parts.findIndex(hasReplyText);
    const thinkingEnd = replyIndex === -1 ? parts.length : replyIndex;

    let firstReasoningIndex = -1;
    for (let index = 0; index < thinkingEnd; index += 1) {
        if (parts[index]?.type === "reasoning") {
            firstReasoningIndex = index;
            break;
        }
    }

    const hasThinkingBlock = firstReasoningIndex !== -1;

    return parts.map((part, index) => {
        const inThinking =
            hasThinkingBlock &&
            index >= firstReasoningIndex &&
            index < thinkingEnd;

        if (part.type === "reasoning") {
            return inThinking ? [CHAIN_OF_THOUGHT, GROUP_REASONING] : [];
        }

        if (part.type === "text") {
            const blank = (part.text ?? "").trim() === "";
            return blank && inThinking ? [CHAIN_OF_THOUGHT, GROUP_BLANK] : [];
        }

        if (part.type === "tool-call") {
            const hidden = HIDDEN_TOOL_NAMES.has(part.toolName ?? "");
            if (hidden) {
                return inThinking
                    ? [CHAIN_OF_THOUGHT, GROUP_TOOL]
                    : [GROUP_TOOL_STANDALONE];
            }
            if (isStandaloneToolCall(part, context)) {
                return [GROUP_TOOL_STANDALONE];
            }
            return inThinking
                ? [CHAIN_OF_THOUGHT, GROUP_TOOL]
                : [GROUP_TOOL_STANDALONE];
        }

        return [];
    });
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
