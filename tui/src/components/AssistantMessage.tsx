/** Assistant message card: renders by parts (markdown / reasoning / tool-call) */
import { useState } from "react";
import type { MessagePart, TuiMessage } from "../stores/chat-store.ts";
import { groupAssistantParts } from "../lib/group-parts.ts";
import { ExploredGroup } from "./ExploredGroup.tsx";
import { MarkdownPart } from "./parts/MarkdownPart.tsx";
import { ReasoningPart } from "./parts/ReasoningPart.tsx";
import { ThinkingSpinner } from "./parts/ThinkingSpinner.tsx";
import { ToolCallPartView } from "./parts/ToolCallPart.tsx";
import { theme } from "../theme.ts";

export function AssistantMessage({ message }: { message: TuiMessage }) {
    const isStreaming = message.status === "streaming";
    const [expanded, setExpanded] = useState<Record<string, boolean>>({});
    const items = groupAssistantParts(message.id, message.parts);

    const toggle = (key: string) =>
        setExpanded((state) => ({
            ...state,
            [key]: !state[key],
        }));

    return (
        <box flexDirection="column" paddingX={2} marginBottom={1}>
            {items.map((item) =>
                item.kind === "explore" ? (
                    <ExploredGroup
                        key={item.key}
                        parts={item.parts}
                        expanded={Boolean(expanded[item.key])}
                        onToggle={() => toggle(item.key)}
                    />
                ) : (
                    <PartView
                        key={`${message.id}:part:${item.index}`}
                        part={item.part}
                        streaming={isStreaming}
                    />
                ),
            )}
            {message.error ? (
                <text fg={theme.error} content={message.error} />
            ) : null}
        </box>
    );
}

function PartView({
    part,
    streaming,
}: {
    part: MessagePart;
    streaming: boolean;
}) {
    switch (part.type) {
        case "text":
            if (!part.text.trim()) {
                return null;
            }
            return (
                <box flexDirection="row">
                    <text fg={theme.success} content="●" flexShrink={0} />
                    <box flexGrow={1} paddingX={1} flexShrink={1}>
                        <MarkdownPart text={part.text} streaming={streaming} />
                    </box>
                </box>
            );
        case "reasoning":
            return <ReasoningPart part={part} />;
        case "tool-call":
            return <ToolCallPartView part={part} />;
        case "pending":
            return <ThinkingSpinner />;
    }
}
