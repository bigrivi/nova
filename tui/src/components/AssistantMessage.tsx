/** Assistant message card: renders by parts (markdown / reasoning / tool-call) */
import type { MessagePart, TuiMessage } from "../stores/chat-store.ts";
import { MarkdownPart } from "./parts/MarkdownPart.tsx";
import { ReasoningPart } from "./parts/ReasoningPart.tsx";
import { ThinkingSpinner } from "./parts/ThinkingSpinner.tsx";
import { ToolCallPartView } from "./parts/ToolCallPart.tsx";
import { theme } from "../theme.ts";

export function AssistantMessage({ message }: { message: TuiMessage }) {
    const isStreaming = message.status === "streaming";

    return (
        <box flexDirection="column" paddingX={2} marginBottom={1}>
            {message.parts.map((part, index) => (
                <PartView key={index} part={part} streaming={isStreaming} />
            ))}
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
