import type { ThreadMessageLike } from "@assistant-ui/react";

import type { NovaJsonObject, NovaMessageRecord } from "../types/nova";
import { randomId } from "./utils";

type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

type ElapsedReasoningPart = { elapsedMs?: number | null };

function reasoningPart(
    text: string,
    elapsedMs: number | null | undefined,
): AssistantPart {
    return {
        type: "reasoning",
        text,
        elapsedMs: elapsedMs ?? null,
    } as AssistantPart & ElapsedReasoningPart;
}

type ToolCallLike = {
    id: string;
    name: string;
    arguments: string;
};

function parseToolCallLike(value: unknown): ToolCallLike | null {
    if (!value || typeof value !== "object") {
        return null;
    }

    const raw = value as Record<string, unknown>;
    const id = String(raw.id ?? "").trim();
    const name = String(raw.name ?? "").trim();
    const argumentsText = String(raw.arguments ?? "").trim();
    if (!name) {
        return null;
    }

    return {
        id: id || randomId(),
        name,
        arguments: argumentsText,
    };
}

function parseJsonObject(value: string): NovaJsonObject {
    const text = value.trim();
    if (!text) {
        return {};
    }

    try {
        const parsed = JSON.parse(text);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as NovaJsonObject)
            : {};
    } catch {
        return {};
    }
}

function parseToolResultContent(content: string | null | undefined): unknown {
    if (!content) return {};
    const text = content.trim();
    if (!text) {
        return {};
    }

    try {
        return JSON.parse(text);
    } catch {
        return { content };
    }
}

export function toThreadMessages(
    messages: NovaMessageRecord[],
): ThreadMessageLike[] {
    const threadMessages: ThreadMessageLike[] = [];
    const toolPartIndexByCallId = new Map<
        string,
        {
            messageIndex: number;
            partIndex: number;
        }
    >();

    const mergedGroupIndices = new Map<string, number>();

    for (const message of messages) {
        if (message.role === "user") {
            const parts: AssistantPart[] = [];
            if (message.images && message.images.length > 0) {
                for (const img of message.images) {
                    parts.push({
                        type: "image" as const,
                        image: `data:image/png;base64,${img}`,
                    });
                }
            }
            if (message.content) {
                parts.push({ type: "text" as const, text: message.content });
            }
            // Backend flags sub-agent completion turns with variant="subagent".
            // Surface it on metadata.custom so the thread renderer can show a
            // compact chip instead of a user bubble (content-prefix fallback
            // covers live-streamed messages, which carry no variant).
            const metadata = message.variant
                ? { custom: { variant: message.variant } }
                : undefined;
            if (parts.length === 1 && parts[0].type === "text") {
                threadMessages.push({
                    id: message.id,
                    role: "user",
                    content: parts[0].text,
                    createdAt: new Date(message.time_created),
                    ...(metadata ? { metadata } : {}),
                });
            } else {
                threadMessages.push({
                    id: message.id,
                    role: "user",
                    content: parts,
                    createdAt: new Date(message.time_created),
                    ...(metadata ? { metadata } : {}),
                });
            }
            continue;
        }

        if (message.role === "assistant") {
            if (message.group_id && mergedGroupIndices.has(message.group_id)) {
                const targetIdx = mergedGroupIndices.get(message.group_id)!;
                const target = threadMessages[targetIdx];
                if (
                    target &&
                    target.role === "assistant" &&
                    typeof target.content !== "string"
                ) {
                    const nextContent = [...target.content];
                    if (message.reasoning_content) {
                        nextContent.push(
                            reasoningPart(
                                message.reasoning_content,
                                message.reasoning_elapsed_ms,
                            ),
                        );
                    }
                    if (message.content) {
                        nextContent.push({
                            type: "text",
                            text: message.content,
                        });
                    }
                    for (const toolCall of message.tool_calls) {
                        const parsed = parseToolCallLike(toolCall);
                        if (!parsed) {
                            continue;
                        }
                        const partIndex = nextContent.length;
                        nextContent.push({
                            type: "tool-call",
                            toolCallId: parsed.id,
                            toolName: parsed.name,
                            args: parseJsonObject(parsed.arguments),
                            argsText: parsed.arguments,
                        });
                        toolPartIndexByCallId.set(parsed.id, {
                            messageIndex: targetIdx,
                            partIndex,
                        });
                    }

                    threadMessages[targetIdx] = {
                        ...target,
                        content: nextContent,
                    };
                }
                continue;
            }

            const content: AssistantPart[] = [];
            if (message.reasoning_content) {
                content.push(
                    reasoningPart(
                        message.reasoning_content,
                        message.reasoning_elapsed_ms,
                    ),
                );
            }
            if (message.content) {
                content.push({ type: "text", text: message.content });
            }

            for (const toolCall of message.tool_calls) {
                const parsed = parseToolCallLike(toolCall);
                if (!parsed) {
                    continue;
                }

                content.push({
                    type: "tool-call",
                    toolCallId: parsed.id,
                    toolName: parsed.name,
                    args: parseJsonObject(parsed.arguments),
                    argsText: parsed.arguments,
                });
            }

            if (content.length === 0) {
                continue;
            }

            const messageIndex = threadMessages.length;

            const assistantMessage: ThreadMessageLike = {
                id: message.id,
                role: "assistant",
                content,
                createdAt: new Date(message.time_created),
            };
            threadMessages.push(assistantMessage);

            if (message.group_id) {
                mergedGroupIndices.set(message.group_id, messageIndex);
            }

            content.forEach((part, partIndex) => {
                if (part.type !== "tool-call" || !part.toolCallId) {
                    return;
                }
                toolPartIndexByCallId.set(part.toolCallId, {
                    messageIndex,
                    partIndex,
                });
            });
            continue;
        }

        if (message.role !== "tool") {
            continue;
        }

        const toolCallId = String(message.tool_call_id ?? "").trim();
        if (!toolCallId) {
            continue;
        }

        const target = toolPartIndexByCallId.get(toolCallId);
        if (!target) {
            continue;
        }

        const assistantMessage = threadMessages[target.messageIndex];
        if (
            !assistantMessage ||
            assistantMessage.role !== "assistant" ||
            typeof assistantMessage.content === "string"
        ) {
            continue;
        }

        const part = assistantMessage.content[target.partIndex];
        if (!part || part.type !== "tool-call") {
            continue;
        }

        const nextContent = [...assistantMessage.content];
        nextContent[target.partIndex] = {
            ...part,
            result: parseToolResultContent(message.content),
            ...(message.error ? { isError: true } : {}),
        };
        threadMessages[target.messageIndex] = {
            ...assistantMessage,
            content: nextContent,
        };
    }

    return threadMessages;
}
