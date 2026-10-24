/** Group consecutive exploration tool calls into one collapsible summary. */
import type { MessagePart, ToolCallPart } from "../stores/chat-store.ts";

export const EXPLORATION_TOOLS = new Set([
    "read",
    "grep",
    "glob",
    "web_search",
    "web_fetch",
]);

export type AssistantRenderItem =
    | { kind: "part"; part: MessagePart; index: number }
    | { kind: "explore"; key: string; parts: ToolCallPart[] };

export function groupAssistantParts(
    messageId: string,
    parts: MessagePart[],
): AssistantRenderItem[] {
    const items: AssistantRenderItem[] = [];
    let current: ToolCallPart[] = [];
    let startIndex = -1;

    const flush = () => {
        if (current.length === 0) return;
        items.push({
            kind: "explore",
            key: `${messageId}:explore:${startIndex}`,
            parts: current,
        });
        current = [];
        startIndex = -1;
    };

    parts.forEach((part, index) => {
        if (part.type === "tool-call" && EXPLORATION_TOOLS.has(part.toolName.toLowerCase())) {
            if (current.length === 0) startIndex = index;
            current.push(part);
            return;
        }
        flush();
        items.push({ kind: "part", part, index });
    });
    flush();
    return items;
}

export function explorationCounts(parts: ToolCallPart[]): {
    search: number;
    read: number;
    fetch: number;
} {
    let search = 0;
    let read = 0;
    let fetch = 0;
    for (const part of parts) {
        const name = part.toolName.toLowerCase();
        if (name === "read") read++;
        else if (name === "web_fetch") fetch++;
        else search++;
    }
    return { search, read, fetch };
}

export function pluralExploration(name: string, count: number): string {
    if (count === 1) return name;
    if (name === "search" || name === "fetch") return `${name}es`;
    return `${name}s`;
}

export function explorationLabel(
    parts: ToolCallPart[],
    completed: boolean,
): string {
    const counts = explorationCounts(parts);
    const pieces: string[] = [];
    if (counts.search > 0)
        pieces.push(`${counts.search} ${pluralExploration("search", counts.search)}`);
    if (counts.read > 0)
        pieces.push(`${counts.read} ${pluralExploration("read", counts.read)}`);
    if (counts.fetch > 0)
        pieces.push(`${counts.fetch} ${pluralExploration("fetch", counts.fetch)}`);
    return `${completed ? "Explored" : "Exploring"}: ${pieces.join(", ")}`;
}

export function explorationCompleted(parts: ToolCallPart[]): boolean {
    return parts.every(
        (part) =>
            part.status === "done" ||
            part.status === "error" ||
            part.status === "blocked",
    );
}