/** History message conversion: NovaMessageRecord → TuiMessage (simplified: restores text/reasoning/tool-call, attaches tool results to the corresponding call) */
import type { NovaMessageRecord } from "../api/types.ts";
import type { MessagePart, TuiMessage } from "../stores/chat-store.ts";

function parseToolArgs(argumentsValue: unknown): string {
    if (typeof argumentsValue === "string") return argumentsValue;
    try {
        return JSON.stringify(argumentsValue, null, 2);
    } catch {
        return String(argumentsValue);
    }
}

export function recordToMessage(record: NovaMessageRecord): TuiMessage {
    if (record.role === "user") {
        return {
            id: record.id,
            role: "user",
            parts: [{ type: "text", text: record.content }],
            status: "done",
            pending: false,
        };
    }
    const parts: MessagePart[] = [];
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
    for (const tc of record.tool_calls) {
        const call = tc as {
            id?: string;
            name?: string;
            arguments?: unknown;
        };
        const rawArgs = call.arguments;
        parts.push({
            type: "tool-call",
            toolCallId: call.id ?? "",
            toolName: call.name ?? "unknown",
            argsText: parseToolArgs(rawArgs),
            args:
                rawArgs != null &&
                typeof rawArgs === "object" &&
                !Array.isArray(rawArgs)
                    ? (rawArgs as Record<string, unknown>)
                    : null,
            outputText: "",
            status: "done",
        });
    }
    return {
        id: record.id,
        role: "assistant",
        parts,
        status: "done",
        pending: false,
    };
}

export function recordsToMessages(records: NovaMessageRecord[]): TuiMessage[] {
    const messages: TuiMessage[] = [];
    const toolOutputById = new Map<string, string>();
    for (const record of records) {
        if (record.role === "tool" && record.tool_call_id) {
            toolOutputById.set(record.tool_call_id, record.content);
        }
    }
    for (const record of records) {
        // tool messages are not standalone messages: their content only serves as the output source of the tool-call part
        if (record.role === "tool") {
            continue;
        }
        const message = recordToMessage(record);
        const withOutput = message.parts.map((part) => {
            if (part.type === "tool-call") {
                const output = toolOutputById.get(part.toolCallId);
                return output !== undefined
                    ? { ...part, outputText: output }
                    : part;
            }
            return part;
        });
        messages.push({ ...message, parts: withOutput });
    }
    return messages;
}
