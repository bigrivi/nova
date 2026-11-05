/** Turn stored `NovaMessageRecord`s back into the transcript parts the UI draws. */
import type { NovaMessageRecord } from "../api/types";
import type { ChatMessage, ChatPart, ToolPart } from "../state/chat";

type ToolCallLike = { id: string; name: string; arguments: string };

function parseToolCall(value: unknown): ToolCallLike | null {
    if (!value || typeof value !== "object") {
        return null;
    }
    const record = value as Record<string, unknown>;
    const name = String(record.name ?? "").trim();
    if (!name) {
        return null;
    }
    return {
        id: String(record.id ?? "").trim() || `tool_${Math.random().toString(36).slice(2, 8)}`,
        name,
        arguments: String(record.arguments ?? "").trim(),
    };
}

function parseToolResult(content: string | null | undefined): unknown {
    if (!content) {
        return {};
    }
    const text = content.trim();
    if (!text) {
        return {};
    }
    try {
        return JSON.parse(text) as unknown;
    } catch {
        return { content };
    }
}

function outputText(result: unknown): string {
    if (typeof result === "string") {
        return result;
    }
    try {
        return JSON.stringify(result, null, 2);
    } catch {
        return String(result);
    }
}

function emptyToolPart(call: ToolCallLike): ToolPart {
    return {
        type: "tool-call",
        toolCallId: call.id,
        toolName: call.name,
        inputText: call.arguments,
        outputText: "",
        status: "done",
    };
}

export function recordsToMessages(
    records: readonly NovaMessageRecord[],
): ChatMessage[] {
    const messages: ChatMessage[] = [];
    const toolPositions = new Map<
        string,
        { messageIndex: number; partIndex: number }
    >();
    const groupIndices = new Map<string, number>();

    records.forEach((record, recordIndex) => {
        if (record.role === "user") {
            const text = record.display_text ?? record.content;
            const images = record.images ?? [];
            messages.push({
                id: record.id || `user_${recordIndex}`,
                role: "user",
                parts: text ? [{ type: "text", text }] : [],
                status: "done",
                ...(record.variant ? { variant: record.variant } : {}),
                ...(images.length > 0
                    ? {
                          attachments: images.map((image, index) => ({
                              kind: "image" as const,
                              uri: image.startsWith("data:")
                                  ? image
                                  : `data:image/png;base64,${image}`,
                              name: `image-${index + 1}`,
                          })),
                      }
                    : {}),
            });
            return;
        }

        if (record.role === "assistant") {
            const parts: ChatPart[] = [];
            if (record.reasoning_content) {
                parts.push({
                    type: "reasoning",
                    text: record.reasoning_content,
                    elapsedMs: record.reasoning_elapsed_ms ?? null,
                    completed: true,
                });
            }
            if (record.content) {
                parts.push({ type: "text", text: record.content });
            }
            for (const raw of record.tool_calls ?? []) {
                const call = parseToolCall(raw);
                if (call) {
                    parts.push(emptyToolPart(call));
                }
            }
            if (parts.length === 0) {
                return;
            }

            const grouped =
                record.group_id != null
                    ? groupIndices.get(record.group_id)
                    : undefined;
            if (grouped !== undefined) {
                const target = messages[grouped];
                if (target) {
                    const start = target.parts.length;
                    target.parts = [...target.parts, ...parts];
                    parts.forEach((part, partIndex) => {
                        if (part.type === "tool-call") {
                            toolPositions.set(part.toolCallId, {
                                messageIndex: grouped,
                                partIndex: start + partIndex,
                            });
                        }
                    });
                }
                return;
            }

            const messageIndex = messages.length;
            messages.push({
                id: record.id || `assistant_${recordIndex}`,
                role: "assistant",
                parts,
                status: "done",
            });
            if (record.group_id) {
                groupIndices.set(record.group_id, messageIndex);
            }
            parts.forEach((part, partIndex) => {
                if (part.type === "tool-call") {
                    toolPositions.set(part.toolCallId, {
                        messageIndex,
                        partIndex,
                    });
                }
            });
            return;
        }

        if (record.role !== "tool") {
            return;
        }
        const toolCallId = String(record.tool_call_id ?? "").trim();
        const position = toolPositions.get(toolCallId);
        if (!position) {
            return;
        }
        const target = messages[position.messageIndex];
        const part = target?.parts[position.partIndex];
        if (!target || !part || part.type !== "tool-call") {
            return;
        }
        const parts = target.parts.slice();
        parts[position.partIndex] = {
            ...part,
            outputText: outputText(parseToolResult(record.content)),
            status: record.error ? "error" : "done",
            ...(record.error ? { error: record.error } : {}),
        };
        messages[position.messageIndex] = { ...target, parts };
    });

    return messages;
}
