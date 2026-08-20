/** Assistant message card: renders by parts (markdown / reasoning / tool-call) */
import type { MessagePart, TuiMessage } from "../stores/chat-store.ts";
import { MarkdownPart } from "./parts/MarkdownPart.tsx";
import { ReasoningPart } from "./parts/ReasoningPart.tsx";
import { ThinkingSpinner } from "./parts/ThinkingSpinner.tsx";
import { ToolCallPartView } from "./parts/ToolCallPart.tsx";

export function AssistantMessage({ message }: { message: TuiMessage }) {
    const isStreaming = message.status === "streaming";
    const awaitingResponse = isStreaming && message.parts.length === 0;

    return (
        <box flexDirection="column" paddingX={2} marginBottom={1}>
            {awaitingResponse ? <ThinkingSpinner /> : null}
            {message.parts.map((part, index) => (
                <PartView key={index} part={part} streaming={isStreaming} />
            ))}
            {message.error ? (
                <text fg="#e5534b" content={message.error} />
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
                    <text fg="#3fb950" content="●" flexShrink={0} />
                    <box flexGrow={1} paddingX={1} flexShrink={1}>
                        <MarkdownPart text={part.text} streaming={streaming} />
                    </box>
                </box>
            );
        case "reasoning":
            return <ReasoningPart part={part} />;
        case "tool-call":
            return <ToolCallPartView part={part} />;
    }
}
