/** Per-tab chat transcripts. The tab id is the key; no active-tab mirror. */
import { create } from "zustand";

import type {
    ApprovalRequest,
    ContextUsage,
} from "../api/types";
import type { AskQuestion } from "../chat/ask";
import type { TodoItem } from "../chat/todo";

export type TextPart = { type: "text"; text: string };

export type ReasoningPart = {
    type: "reasoning";
    text: string;
    elapsedMs: number | null;
    completed: boolean;
};

export type ToolPart = {
    type: "tool-call";
    toolCallId: string;
    toolName: string;
    inputText: string;
    outputText: string;
    status: "running" | "done" | "error";
    error?: string;
};

export type ChatPart = TextPart | ReasoningPart | ToolPart;

export type RetryState = {
    attempt: number;
    total: number;
    waitSeconds: number;
    reason: string;
};

export type ChatMessage = {
    id: string;
    role: "user" | "assistant";
    parts: ChatPart[];
    status: "streaming" | "done" | "error";
    variant?: string;
    error?: string;
    /** Provider retry line while the first content is still pending. */
    retry?: RetryState | null;
    /** Local previews of attachments sent with a user turn. */
    attachments?: Array<{
        kind: "image" | "document";
        uri?: string;
        name: string;
    }>;
};

export type ChatSlice = {
    sessionId: string | null;
    agentKey: string | null;
    projectId: string | null;
    /** Route option id the session was opened with; null for drafts. */
    modelId: string | null;
    effort: string | null;
    messages: ChatMessage[];
    streaming: boolean;
    error: string | null;
    approval: ApprovalRequest | null;
    context: ContextUsage | null;
    requiresInput: string | null;
    ask: AskQuestion[] | null;
    todos: TodoItem[] | null;
    compacting: boolean;
    compactionSummary: string;
};

type ChatStore = {
    byId: Record<string, ChatSlice>;
    appendUserMessage: (
        tabId: string,
        text: string,
        variant?: string,
        attachments?: Array<{
            kind: "image" | "document";
            uri?: string;
            name: string;
        }>,
    ) => void;
    startAssistant: (tabId: string) => string;
    setRetry: (tabId: string, retry: RetryState | null) => void;
    appendText: (tabId: string, delta: string) => void;
    appendReasoning: (tabId: string, delta: string) => void;
    endReasoning: (tabId: string, elapsedMs: number) => void;
    upsertTool: (
        tabId: string,
        tool: {
            toolCallId: string;
            toolName?: string;
            inputText?: string;
            outputText?: string;
            status?: ToolPart["status"];
            error?: string;
        },
    ) => void;
    finishTurn: (tabId: string, error?: string) => void;
    dropEmptyAssistant: (tabId: string) => void;
    loadHistory: (
        tabId: string,
        sessionId: string,
        messages: ChatMessage[],
    ) => void;
    setSessionId: (tabId: string, sessionId: string) => void;
    setAgent: (tabId: string, agentKey: string | null) => void;
    setModel: (tabId: string, modelId: string | null) => void;
    setEffort: (tabId: string, effort: string | null) => void;
    setProjectId: (tabId: string, projectId: string | null) => void;
    setApproval: (tabId: string, approval: ApprovalRequest | null) => void;
    setContext: (tabId: string, context: ContextUsage) => void;
    setRequiresInput: (tabId: string, message: string | null) => void;
    setAsk: (tabId: string, questions: AskQuestion[] | null) => void;
    setTodos: (tabId: string, todos: TodoItem[] | null) => void;
    setCompacting: (tabId: string, compacting: boolean) => void;
    appendCompaction: (tabId: string, delta: string) => void;
    setError: (tabId: string, error: string | null) => void;
    remove: (tabId: string) => void;
    reset: () => void;
};

export function emptySlice(): ChatSlice {
    return {
        sessionId: null,
        agentKey: null,
        projectId: null,
        modelId: null,
        effort: null,
        messages: [],
        streaming: false,
        error: null,
        approval: null,
        context: null,
        requiresInput: null,
        ask: null,
        todos: null,
        compacting: false,
        compactionSummary: "",
    };
}

function randomId(prefix: string): string {
    return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

function lastAssistantIndex(messages: readonly ChatMessage[]): number {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        if (messages[index]!.role === "assistant") {
            return index;
        }
    }
    return -1;
}

function patchLastAssistant(
    slice: ChatSlice,
    patch: (message: ChatMessage) => ChatMessage,
): ChatSlice {
    const index = lastAssistantIndex(slice.messages);
    if (index === -1) {
        return slice;
    }
    const patched = patch(slice.messages[index]!);
    if (patched === slice.messages[index]) {
        return slice;
    }
    const messages = slice.messages.slice();
    messages[index] = patched;
    return { ...slice, messages };
}

function appendPart(
    message: ChatMessage,
    part: ChatPart,
): ChatMessage {
    const parts = message.parts.slice();
    const last = parts[parts.length - 1];
    if (last && last.type === "text" && part.type === "text") {
        parts[parts.length - 1] = {
            type: "text",
            text: last.text + part.text,
        };
    } else if (
        last &&
        last.type === "reasoning" &&
        part.type === "reasoning"
    ) {
        parts[parts.length - 1] = {
            ...last,
            text: last.text + part.text,
        };
    } else {
        parts.push(part);
    }
    return { ...message, parts };
}

export const useChat = create<ChatStore>((set) => ({
    byId: {},

    appendUserMessage: (tabId, text, variant, attachments) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            const message: ChatMessage = {
                id: randomId("user"),
                role: "user",
                parts: [{ type: "text", text }],
                status: "done",
                ...(variant ? { variant } : {}),
                ...(attachments && attachments.length > 0
                    ? { attachments }
                    : {}),
            };
            return {
                byId: {
                    ...state.byId,
                    [tabId]: {
                        ...current,
                        messages: [...current.messages, message],
                        error: null,
                    },
                },
            };
        }),

    startAssistant: (tabId) => {
        const id = randomId("assistant");
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            const message: ChatMessage = {
                id,
                role: "assistant",
                parts: [],
                status: "streaming",
                retry: null,
            };
            return {
                byId: {
                    ...state.byId,
                    [tabId]: {
                        ...current,
                        messages: [...current.messages, message],
                        streaming: true,
                        error: null,
                        approval: null,
                        requiresInput: null,
                        ask: null,
                        compacting: false,
                        compactionSummary: "",
                    },
                },
            };
        });
        return id;
    },

    setRetry: (tabId, retry) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: patchLastAssistant(current, (message) => {
                        if (message.retry === retry || (message.retry == null && retry == null)) {
                            return message;
                        }
                        return { ...message, retry };
                    }),
                },
            };
        }),

    appendText: (tabId, delta) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            const index = lastAssistantIndex(current.messages);
            if (index === -1) {
                return state;
            }
            const messages = current.messages.slice();
            messages[index] = appendPart(messages[index]!, {
                type: "text",
                text: delta,
            });
            return {
                byId: { ...state.byId, [tabId]: { ...current, messages } },
            };
        }),

    appendReasoning: (tabId, delta) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            const index = lastAssistantIndex(current.messages);
            if (index === -1) {
                return state;
            }
            const messages = current.messages.slice();
            messages[index] = appendPart(messages[index]!, {
                type: "reasoning",
                text: delta,
                elapsedMs: null,
                completed: false,
            });
            return {
                byId: { ...state.byId, [tabId]: { ...current, messages } },
            };
        }),

    endReasoning: (tabId, elapsedMs) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: patchLastAssistant(current, (message) => {
                        const parts = message.parts.slice();
                        for (let index = parts.length - 1; index >= 0; index -= 1) {
                            const part = parts[index]!;
                            if (part.type === "reasoning") {
                                parts[index] = {
                                    ...part,
                                    elapsedMs,
                                    completed: true,
                                };
                                break;
                            }
                        }
                        return { ...message, parts };
                    }),
                },
            };
        }),

    upsertTool: (tabId, tool) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: patchLastAssistant(current, (message) => {
                        const parts = message.parts.slice();
                        const index = parts.findIndex(
                            (part) =>
                                part.type === "tool-call" &&
                                part.toolCallId === tool.toolCallId,
                        );
                        if (index === -1) {
                            parts.push({
                                type: "tool-call",
                                toolCallId: tool.toolCallId,
                                toolName: tool.toolName ?? "tool",
                                inputText: tool.inputText ?? "",
                                outputText: tool.outputText ?? "",
                                status: tool.status ?? "running",
                                ...(tool.error ? { error: tool.error } : {}),
                            });
                        } else {
                            const existing = parts[index] as ToolPart;
                            parts[index] = {
                                ...existing,
                                toolName: tool.toolName ?? existing.toolName,
                                inputText:
                                    tool.inputText ?? existing.inputText,
                                outputText:
                                    tool.outputText ?? existing.outputText,
                                status: tool.status ?? existing.status,
                                ...(tool.error
                                    ? { error: tool.error }
                                    : {}),
                            };
                        }
                        return { ...message, parts };
                    }),
                },
            };
        }),

    finishTurn: (tabId, error) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: {
                        ...patchLastAssistant(current, (message) => ({
                            ...message,
                            status: error ? "error" : "done",
                            retry: null,
                            ...(error ? { error } : {}),
                        })),
                        streaming: false,
                        error: error ?? null,
                        approval: null,
                        compacting: false,
                    },
                },
            };
        }),

    dropEmptyAssistant: (tabId) =>
        set((state) => {
            const current = state.byId[tabId];
            if (!current) {
                return state;
            }
            const index = lastAssistantIndex(current.messages);
            if (index === -1) {
                return state;
            }
            const message = current.messages[index]!;
            if (message.parts.length > 0) {
                return state;
            }
            const messages = current.messages.slice();
            messages.splice(index, 1);
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, messages, streaming: false },
                },
            };
        }),

    loadHistory: (tabId, sessionId, messages) =>
        set((state) => {
            const current = state.byId[tabId];
            return {
                byId: {
                    ...state.byId,
                    [tabId]: {
                        ...emptySlice(),
                        sessionId,
                        agentKey: current?.agentKey ?? null,
                        projectId: current?.projectId ?? null,
                        modelId: current?.modelId ?? null,
                        effort: current?.effort ?? null,
                        messages,
                    },
                },
            };
        }),

    setSessionId: (tabId, sessionId) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, sessionId },
                },
            };
        }),

    setAgent: (tabId, agentKey) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, agentKey },
                },
            };
        }),

    setModel: (tabId, modelId) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, modelId },
                },
            };
        }),

    setEffort: (tabId, effort) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, effort },
                },
            };
        }),

    setProjectId: (tabId, projectId) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, projectId },
                },
            };
        }),

    setApproval: (tabId, approval) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: {
                        ...current,
                        approval,
                        requiresInput: approval ? null : current.requiresInput,
                    },
                },
            };
        }),

    setContext: (tabId, context) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, context },
                },
            };
        }),

    setRequiresInput: (tabId, message) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, requiresInput: message },
                },
            };
        }),

    setAsk: (tabId, questions) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, ask: questions },
                },
            };
        }),

    setTodos: (tabId, todos) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, todos },
                },
            };
        }),

    setCompacting: (tabId, compacting) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: compacting
                        ? {
                              ...current,
                              compacting: true,
                              compactionSummary: "",
                          }
                        : { ...current, compacting: false },
                },
            };
        }),

    appendCompaction: (tabId, delta) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: {
                        ...current,
                        compactionSummary:
                            current.compactionSummary + delta,
                    },
                },
            };
        }),

    setError: (tabId, error) =>
        set((state) => {
            const current = state.byId[tabId] ?? emptySlice();
            return {
                byId: {
                    ...state.byId,
                    [tabId]: { ...current, error },
                },
            };
        }),

    remove: (tabId) =>
        set((state) => {
            if (!(tabId in state.byId)) {
                return state;
            }
            const byId = { ...state.byId };
            delete byId[tabId];
            return { byId };
        }),

    reset: () => set({ byId: {} }),
}));

export function chatSlice(tabId: string | null): ChatSlice {
    if (!tabId) {
        return emptySlice();
    }
    return useChat.getState().byId[tabId] ?? emptySlice();
}
