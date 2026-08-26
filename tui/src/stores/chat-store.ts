/** Chat global state: messages (parts structure), session ID, streaming state (zustand) */
import { create } from "zustand";

export type TextPart = { type: "text"; text: string };
export type ReasoningPart = {
    type: "reasoning";
    text: string;
    elapsedMs: number | null;
    completed: boolean;
};
export type ToolCallPart = {
    type: "tool-call";
    toolCallId: string;
    toolName: string;
    argsText: string;
    /** Raw args object, for summary extraction; null for tools without structured args (e.g. ask_user) */
    args: Record<string, unknown> | null;
    outputText: string;
    status: "running" | "blocked" | "done" | "error";
    error?: string;
};
export type PendingPart = { type: "pending" };
export type MessagePart = TextPart | ReasoningPart | ToolCallPart | PendingPart;

export type TuiMessage = {
    id: string;
    role: "user" | "assistant";
    parts: MessagePart[];
    status: "streaming" | "done" | "error";
    error?: string;
};

/** Model selection for this conversation (P3: taken over by the model selection screen) */
export const DEFAULT_PROVIDER = "opencode";
export const DEFAULT_MODEL = "deepseek-v4-flash-free";

type ChatState = {
    messages: TuiMessage[];
    sessionId: string | null;
    isStreaming: boolean;
    provider: string;
    model: string;

    setSessionId: (sessionId: string) => void;
    setPending: (messageId: string, pending: boolean) => void;
    addUserMessage: (text: string) => void;
    startAssistantMessage: () => string;
    startTextPart: (messageId: string) => void;
    appendTextDelta: (messageId: string, delta: string) => void;
    startReasoningPart: (messageId: string) => void;
    appendReasoningDelta: (messageId: string, delta: string) => void;
    endReasoningPart: (messageId: string, elapsedMs: number | null) => void;
    startToolCall: (
        messageId: string,
        tool: { toolCallId: string; toolName: string },
    ) => void;
    setToolInput: (
        messageId: string,
        toolCallId: string,
        input: unknown,
    ) => void;
    setToolOutput: (
        messageId: string,
        toolCallId: string,
        output: unknown,
    ) => void;
    setToolStatus: (
        messageId: string,
        toolCallId: string,
        status: ToolCallPart["status"],
    ) => void;
    failToolCall: (
        messageId: string,
        toolCallId: string,
        message: string,
    ) => void;
    completeStream: () => void;
    failStream: (error: string) => void;
    loadHistory: (sessionId: string, messages: TuiMessage[]) => void;
    reset: () => void;
};

function makeId(): string {
    return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function patchMessage(
    messages: TuiMessage[],
    messageId: string,
    patch: (msg: TuiMessage) => TuiMessage,
): TuiMessage[] {
    return messages.map((msg) => (msg.id === messageId ? patch(msg) : msg));
}

function lastPartOfType<T extends MessagePart["type"]>(
    parts: MessagePart[],
    type: T,
): (MessagePart & { type: T }) | null {
    for (let i = parts.length - 1; i >= 0; i--) {
        if (parts[i]?.type === type) {
            return parts[i] as MessagePart & { type: T };
        }
    }
    return null;
}

/** Display text for tool output/args (object → recursively unwrap content field; otherwise compact JSON) */
function toDisplayText(value: unknown): string {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "object") {
        const content = (value as Record<string, unknown>).content;
        if (content !== undefined) {
            return toDisplayText(content);
        }
    }
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

/** Extract tool args as a plain object for summary display; return null for non-objects (e.g. arrays/strings) */
function toArgsObject(value: unknown): Record<string, unknown> | null {
    if (value == null || typeof value !== "object" || Array.isArray(value)) {
        return null;
    }
    return value as Record<string, unknown>;
}

export const useChatStore = create<ChatState>((set) => ({
    messages: [],
    sessionId: null,
    isStreaming: false,
    provider: DEFAULT_PROVIDER,
    model: DEFAULT_MODEL,

    setSessionId: (sessionId) => set({ sessionId }),

    setPending: (messageId, pending) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => {
                const hasPending = msg.parts.some((p) => p.type === "pending");
                if (pending && !hasPending) {
                    return {
                        ...msg,
                        parts: [...msg.parts, { type: "pending" }],
                    };
                }
                if (!pending && hasPending) {
                    return {
                        ...msg,
                        parts: msg.parts.filter((p) => p.type !== "pending"),
                    };
                }
                return msg;
            }),
        })),

    addUserMessage: (text) =>
        set((state) => ({
            messages: [
                ...state.messages,
                {
                    id: makeId(),
                    role: "user",
                    parts: [{ type: "text", text }],
                    status: "done",
                },
            ],
        })),

    startAssistantMessage: () => {
        const id = makeId();
        set((state) => ({
            isStreaming: true,
            messages: [
                ...state.messages,
                {
                    id,
                    role: "assistant",
                    parts: [{ type: "pending" }],
                    status: "streaming",
                },
            ],
        }));
        return id;
    },

    startTextPart: (messageId) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => {
                const filtered = msg.parts.filter((p) => p.type !== "pending");
                const last = filtered[filtered.length - 1];
                if (last?.type === "text") {
                    return filtered === msg.parts
                        ? msg
                        : { ...msg, parts: filtered };
                }
                return {
                    ...msg,
                    parts: [...filtered, { type: "text", text: "" }],
                };
            }),
        })),

    appendTextDelta: (messageId, delta) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => {
                const existing = lastPartOfType(msg.parts, "text");
                if (existing) {
                    return {
                        ...msg,
                        parts: msg.parts.map((part) =>
                            part === existing
                                ? { ...part, text: part.text + delta }
                                : part,
                        ),
                    };
                }
                return {
                    ...msg,
                    parts: [...msg.parts, { type: "text", text: delta }],
                };
            }),
        })),

    startReasoningPart: (messageId) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => {
                const filtered = msg.parts.filter((p) => p.type !== "pending");
                const last = filtered[filtered.length - 1];
                if (last?.type === "reasoning") {
                    return filtered === msg.parts
                        ? msg
                        : { ...msg, parts: filtered };
                }
                return {
                    ...msg,
                    parts: [
                        ...filtered,
                        {
                            type: "reasoning",
                            text: "",
                            elapsedMs: null,
                            completed: false,
                        },
                    ],
                };
            }),
        })),

    appendReasoningDelta: (messageId, delta) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => {
                const reasoning = lastPartOfType(msg.parts, "reasoning");
                if (!reasoning) {
                    return {
                        ...msg,
                        parts: [
                            ...msg.parts,
                            {
                                type: "reasoning",
                                text: delta,
                                elapsedMs: null,
                                completed: false,
                            },
                        ],
                    };
                }
                return {
                    ...msg,
                    parts: msg.parts.map((part) =>
                        part === reasoning
                            ? { ...part, text: part.text + delta }
                            : part,
                    ),
                };
            }),
        })),

    endReasoningPart: (messageId, elapsedMs) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => {
                const reasoning = lastPartOfType(msg.parts, "reasoning");
                if (!reasoning) {
                    return msg;
                }
                return {
                    ...msg,
                    parts: msg.parts.map((part) =>
                        part === reasoning
                            ? { ...part, completed: true, elapsedMs }
                            : part,
                    ),
                };
            }),
        })),

    startToolCall: (messageId, tool) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => ({
                ...msg,
                parts: [
                    ...msg.parts.filter(
                        (part) =>
                            part.type !== "pending" &&
                            (part.type !== "text" || part.text.trim() !== ""),
                    ),
                    {
                        type: "tool-call",
                        toolCallId: tool.toolCallId,
                        toolName: tool.toolName,
                        argsText: "",
                        args: null,
                        outputText: "",
                        status: "running",
                    },
                ],
            })),
        })),

    setToolInput: (messageId, toolCallId, input) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => ({
                ...msg,
                parts: msg.parts.map((part) =>
                    part.type === "tool-call" && part.toolCallId === toolCallId
                        ? {
                              ...part,
                              argsText: toDisplayText(input),
                              args: toArgsObject(input),
                          }
                        : part,
                ),
            })),
        })),

    setToolOutput: (messageId, toolCallId, output) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => ({
                ...msg,
                parts: msg.parts.map((part) =>
                    part.type === "tool-call" && part.toolCallId === toolCallId
                        ? {
                              ...part,
                              outputText: toDisplayText(output),
                              status: "done",
                          }
                        : part,
                ),
            })),
        })),

    setToolStatus: (messageId, toolCallId, status) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => ({
                ...msg,
                parts: msg.parts.map((part) =>
                    part.type === "tool-call" && part.toolCallId === toolCallId
                        ? { ...part, status }
                        : part,
                ),
            })),
        })),

    failToolCall: (messageId, toolCallId, message) =>
        set((state) => ({
            messages: patchMessage(state.messages, messageId, (msg) => ({
                ...msg,
                parts: msg.parts.map((part) =>
                    part.type === "tool-call" && part.toolCallId === toolCallId
                        ? { ...part, status: "error", error: message }
                        : part,
                ),
            })),
        })),

    completeStream: () =>
        set((state) => ({
            isStreaming: false,
            messages: state.messages.map((msg) =>
                msg.status === "streaming"
                    ? {
                          ...msg,
                          status: "done",
                          parts: msg.parts.filter((p) => p.type !== "pending"),
                      }
                    : msg,
            ),
        })),

    failStream: (error) =>
        set((state) => ({
            isStreaming: false,
            messages: state.messages.map((msg) =>
                msg.status === "streaming"
                    ? {
                          ...msg,
                          status: "error",
                          error,
                          parts: msg.parts.filter((p) => p.type !== "pending"),
                      }
                    : msg,
            ),
        })),

    loadHistory: (sessionId, messages) =>
        set({ sessionId, messages, isStreaming: false }),

    reset: () => set({ messages: [], sessionId: null, isStreaming: false }),
}));

/** Read the latest state for stream logic (avoid closures capturing stale values) */
export const getChatState = () => useChatStore.getState();
