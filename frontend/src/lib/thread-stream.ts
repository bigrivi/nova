import type { ThreadMessageLike } from "@assistant-ui/react";

import type {
    NovaJsonObject,
    NovaJsonValue,
    NovaStreamEvent,
} from "../types/nova";

export type StreamPatchContext = {
    assistantMessageId: string;
};

export type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

export type ToolCallPatch = {
    toolCallId: string;
    toolName?: string;
    input?: NovaJsonObject;
    output?: NovaJsonValue;
    isError?: boolean;
};

export function setAssistantText(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    updater: (text: string) => string,
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];
        const textPartIndex = parts.findLastIndex(
            (part) => part.type === "text",
        );
        const currentText =
            textPartIndex >= 0 && parts[textPartIndex]?.type === "text"
                ? parts[textPartIndex].text
                : "";
        const nextText = updater(currentText);

        if (textPartIndex >= 0) {
            parts[textPartIndex] = { type: "text", text: nextText };
        } else if (nextText) {
            parts.push({ type: "text", text: nextText });
        }

        return {
            ...message,
            content: parts,
        };
    });
}

export function setAssistantReasoning(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    updater: (text: string) => string,
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];

        const reasoningIndex = parts.findLastIndex(
            (part) => part.type === "reasoning",
        );
        const currentText =
            reasoningIndex >= 0 && parts[reasoningIndex]?.type === "reasoning"
                ? parts[reasoningIndex].text
                : "";
        const nextText = updater(currentText);

        if (reasoningIndex >= 0) {
            parts[reasoningIndex] = {
                ...parts[reasoningIndex],
                type: "reasoning",
                text: nextText,
            };
        } else if (nextText) {
            parts.push({ type: "reasoning", text: nextText });
        }

        return {
            ...message,
            content: parts,
        };
    });
}

export function setAssistantReasoningElapsed(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    elapsedMs: number,
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];

        const reasoningIndex = parts.findLastIndex(
            (part) => part.type === "reasoning",
        );
        const reasoningPart = parts[reasoningIndex];
        if (!reasoningPart || reasoningPart.type !== "reasoning") {
            return message;
        }

        const nextReasoningPart: AssistantPart & { elapsedMs: number } = {
            ...reasoningPart,
            type: "reasoning",
            text: reasoningPart.text,
            elapsedMs,
        };
        parts[reasoningIndex] = nextReasoningPart;

        return {
            ...message,
            content: parts,
        };
    });
}

export function startAssistantTextPart(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
) {
    return messages.map((msg) => {
        if (msg.id !== assistantMessageId || msg.role !== "assistant")
            return msg;
        const parts =
            typeof msg.content === "string"
                ? msg.content
                    ? [
                          {
                              type: "text" as const,
                              text: msg.content,
                          },
                      ]
                    : []
                : [...msg.content];
        parts.push({ type: "text" as const, text: "" });
        return { ...msg, content: parts };
    });
}

export function startAssistantReasoningPart(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
) {
    return messages.map((msg) => {
        if (msg.id !== assistantMessageId || msg.role !== "assistant")
            return msg;
        const parts =
            typeof msg.content === "string"
                ? msg.content
                    ? [
                          {
                              type: "text" as const,
                              text: msg.content,
                          },
                      ]
                    : []
                : [...msg.content];
        parts.push({
            type: "reasoning" as const,
            text: "",
        });
        return { ...msg, content: parts };
    });
}

export function upsertAssistantToolCall(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    payload: {
        toolCallId: string;
        toolName?: string;
        input?: NovaJsonObject;
        output?: unknown;
        isError?: boolean;
    },
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];
        const toolIndex = parts.findIndex(
            (part) =>
                part.type === "tool-call" &&
                part.toolCallId === payload.toolCallId,
        );

        const current =
            toolIndex >= 0 && parts[toolIndex]?.type === "tool-call"
                ? parts[toolIndex]
                : null;

        const nextPart: AssistantPart = {
            type: "tool-call",
            toolCallId: payload.toolCallId,
            toolName: payload.toolName || current?.toolName || "tool",
            args: payload.input ?? current?.args ?? {},
            argsText:
                payload.input !== undefined
                    ? JSON.stringify(payload.input)
                    : (current?.argsText ?? ""),
            ...(payload.output !== undefined
                ? { result: payload.output }
                : current?.result !== undefined
                  ? { result: current.result }
                  : {}),
            ...(payload.isError !== undefined
                ? { isError: payload.isError }
                : current?.isError !== undefined
                  ? { isError: current.isError }
                  : {}),
        };

        if (toolIndex >= 0) {
            parts[toolIndex] = nextPart;
        } else {
            parts.push(nextPart);
        }

        return {
            ...message,
            content: parts,
        };
    });
}

export function extractSessionId(event: NovaStreamEvent): string {
    return String(event.data?.sessionId || "");
}

export function extractToolErrorCallId(event: NovaStreamEvent): string {
    return String(event.data?.toolCallId ?? "");
}

export function extractReasoningElapsedMs(
    event: NovaStreamEvent,
): number | null {
    return event.elapsedMs ?? null;
}

export type ApprovalRequest = {
    requestId: string;
    command: string;
    description: string;
};

export function extractApprovalRequest(event: NovaStreamEvent): ApprovalRequest {
    return {
        requestId: String(event.data?.requestId || ""),
        command: String(event.data?.command || ""),
        description: String(event.data?.description || ""),
    };
}

export function throwStreamError(event: NovaStreamEvent): never {
    throw new Error(event.errorText || "Unknown error");
}

export type StreamSideEffect =
    | { kind: "ask-user"; input: unknown }
    | { kind: "todo-active"; input: unknown };

export function describeStreamSideEffects(
    event: NovaStreamEvent,
): StreamSideEffect[] {
    if (event.type !== "tool-input-available" || !event.toolCallId) {
        return [];
    }
    const effects: StreamSideEffect[] = [];
    if (event.toolName === "ask_user") {
        effects.push({ kind: "ask-user", input: event.input });
    }
    if (event.toolName === "todo_write") {
        effects.push({ kind: "todo-active", input: event.input });
    }
    return effects;
}

export function parseSseFrame(frame: string): {
    sequence: number | null;
    payload: string | null;
} {
    let sequence: number | null = null;
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
        if (line.startsWith("id:")) {
            const parsed = Number.parseInt(line.slice(3).trim(), 10);
            if (Number.isSafeInteger(parsed) && parsed > 0) {
                sequence = parsed;
            }
        } else if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trimStart());
        }
    }
    const payload = dataLines.join("\n");
    if (!payload || payload === "[DONE]") {
        return { sequence, payload: null };
    }
    return { sequence, payload };
}

export function applyStreamEventOnce(
    messages: ThreadMessageLike[],
    event: NovaStreamEvent,
    context: StreamPatchContext,
    seenSequences: Set<number>,
): { messages: ThreadMessageLike[]; applied: boolean } {
    const sequence = event.sequence;
    if (sequence != null) {
        if (seenSequences.has(sequence)) {
            return { messages, applied: false };
        }
        seenSequences.add(sequence);
    }
    return {
        messages: applyStreamEvent(messages, event, context),
        applied: true,
    };
}

export function mergeMessagesById(
    existing: ThreadMessageLike[],
    incoming: ThreadMessageLike[],
): ThreadMessageLike[] {
    if (incoming.length === 0) {
        return existing;
    }
    const ids = new Set(existing.map((message) => message.id));
    const fresh = incoming.filter((message) => !ids.has(message.id));
    if (fresh.length === 0) {
        return existing;
    }
    return [...existing, ...fresh];
}

export function applyStreamEvent(
    messages: ThreadMessageLike[],
    event: NovaStreamEvent,
    context: StreamPatchContext,
): ThreadMessageLike[] {
    const assistantMessageId = context.assistantMessageId;

    if (event.type === "text-start") {
        return startAssistantTextPart(messages, assistantMessageId);
    }

    if (event.type === "text-delta") {
        return setAssistantText(messages, assistantMessageId, (text) => text + (event.delta || ""));
    }

    if (event.type === "reasoning-start") {
        return startAssistantReasoningPart(messages, assistantMessageId);
    }

    if (event.type === "reasoning-delta") {
        return setAssistantReasoning(
            messages,
            assistantMessageId,
            (text) => text + (event.delta || ""),
        );
    }

    if (event.type === "reasoning-end") {
        const elapsedMs = extractReasoningElapsedMs(event);
        if (elapsedMs == null) {
            return messages;
        }
        return setAssistantReasoningElapsed(
            messages,
            assistantMessageId,
            elapsedMs,
        );
    }

    if (event.type === "tool-input-start") {
        if (!event.toolCallId) {
            return messages;
        }
        return upsertAssistantToolCall(messages, assistantMessageId, {
            toolCallId: event.toolCallId,
            toolName: event.toolName,
        });
    }

    if (event.type === "tool-input-available") {
        if (!event.toolCallId) {
            return messages;
        }
        return upsertAssistantToolCall(messages, assistantMessageId, {
            toolCallId: event.toolCallId,
            toolName: event.toolName,
            input: event.input,
        });
    }

    if (event.type === "tool-output-available") {
        if (!event.toolCallId) {
            return messages;
        }
        return upsertAssistantToolCall(messages, assistantMessageId, {
            toolCallId: event.toolCallId,
            output: event.output,
        });
    }

    if (event.type === "data-nova-tool-error") {
        const toolCallId = extractToolErrorCallId(event);
        if (!toolCallId) {
            return messages;
        }
        return upsertAssistantToolCall(messages, assistantMessageId, {
            toolCallId,
            isError: true,
        });
    }

    if (event.type === "error") {
        throwStreamError(event);
    }

    return messages;
}
