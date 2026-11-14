/** Chat state: messages (parts structure), session, streaming state, per-tab slices.
 *
 *  The top-level fields are always the *active* tab's slice, which keeps every
 *  transcript reader unchanged. `byId` holds the inactive tabs so a background
 *  stream can keep writing while another tab is on screen.
 */
import { create } from "zustand";
import { useTabStore } from "./tab-store.ts";

export type TextPart = {
    type: "text";
    text: string;
    /** Attachment names to show under the bubble; the payload travels separately. */
    images?: string[];
};
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
    /** Backend message id of a server-injected wake turn, for replay dedup. */
    wakeFor?: string;
    /** Server-set marker for messages the user did not type (e.g. subagent). */
    variant?: string;
};

/** A transport retry the provider announced: it is still waiting, and this is why. */
export type RetryState = {
    /** 1-based: the attempt that just failed. */
    attempt: number;
    /** The budget that attempt is counted against. */
    total: number;
    /** How long the provider will wait before trying again. */
    waitSeconds: number;
    /** The upstream's own words, already unwrapped from its JSON envelope. */
    reason: string;
};

/** The transcript state one tab owns. */
export type ChatSlice = {
    messages: TuiMessage[];
    sessionId: string | null;
    isStreaming: boolean;
    provider: string;
    model: string;
    reasoningEffort: string;
    agentKey: string;
    agentName: string;
    retry: RetryState | null;
};

export type RouteSelection = {
    provider: string;
    model: string;
    reasoningEffort?: string;
};

/** Model selection for this conversation (P3: taken over by the model selection screen) */
export const DEFAULT_PROVIDER = "";
export const DEFAULT_MODEL = "";
export const DEFAULT_AGENT_KEY = "main";

type ChatState = ChatSlice & {
    byId: Record<string, ChatSlice>;

    setSessionId: (sessionId: string, tabId?: string | null) => void;
    setRetry: (retry: RetryState | null, tabId?: string | null) => void;
    setPending: (
        messageId: string,
        pending: boolean,
        tabId?: string | null,
    ) => void;
    addUserMessage: (
        text: string,
        images?: string[],
        tabId?: string | null,
    ) => void;
    insertWakeMessage: (
        text: string,
        wakeFor: string,
        variant?: string,
        tabId?: string | null,
    ) => void;
    startAssistantMessage: (tabId?: string | null) => string;
    startTextPart: (messageId: string, tabId?: string | null) => void;
    appendTextDelta: (
        messageId: string,
        delta: string,
        tabId?: string | null,
    ) => void;
    startReasoningPart: (messageId: string, tabId?: string | null) => void;
    appendReasoningDelta: (
        messageId: string,
        delta: string,
        tabId?: string | null,
    ) => void;
    endReasoningPart: (
        messageId: string,
        elapsedMs: number | null,
        tabId?: string | null,
    ) => void;
    startToolCall: (
        messageId: string,
        tool: { toolCallId: string; toolName: string },
        tabId?: string | null,
    ) => void;
    setToolInput: (
        messageId: string,
        toolCallId: string,
        input: unknown,
        tabId?: string | null,
    ) => void;
    setToolOutput: (
        messageId: string,
        toolCallId: string,
        output: unknown,
        tabId?: string | null,
    ) => void;
    setToolStatus: (
        messageId: string,
        toolCallId: string,
        status: ToolCallPart["status"],
        tabId?: string | null,
    ) => void;
    failToolCall: (
        messageId: string,
        toolCallId: string,
        message: string,
        tabId?: string | null,
    ) => void;
    completeStream: (tabId?: string | null) => void;
    failStream: (error: string, tabId?: string | null) => void;
    dropMessage: (messageId: string, tabId?: string | null) => void;
    /** Replace the text of a message in place, for an edited question. */
    replaceMessageText: (
        messageId: string,
        text: string,
        tabId?: string | null,
    ) => void;
    /** Drop every message after *messageId*, for an edited question. */
    dropMessagesAfter: (messageId: string, tabId?: string | null) => void;
    resetAssistantMessage: (
        messageId: string,
        tabId?: string | null,
    ) => void;
    loadHistory: (
        sessionId: string,
        messages: TuiMessage[],
        tabId?: string | null,
    ) => void;
    setRoute: (route: RouteSelection, tabId?: string | null) => void;
    setAgent: (
        agentKey: string,
        agentName: string,
        tabId?: string | null,
    ) => void;
    clearMessages: (tabId?: string | null) => void;
    activate: (nextId: string | null, previousId: string | null) => void;
    remove: (tabId: string) => void;
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

/** Patch one tool-call part in a message, leaving every other part untouched. */
function patchToolPart(
    messages: TuiMessage[],
    messageId: string,
    toolCallId: string,
    patch: (part: ToolCallPart) => ToolCallPart,
): TuiMessage[] {
    return patchMessage(messages, messageId, (msg) => ({
        ...msg,
        parts: msg.parts.map((part) =>
            part.type === "tool-call" && part.toolCallId === toolCallId
                ? patch(part)
                : part,
        ),
    }));
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

/** Text shown for a tool call the stream ended under, so the block stops spinning. */
const UNFINISHED_TOOL_ERROR = "The turn ended before this tool returned.";

/** Resolve parts a finished stream can no longer paint.
 *
 * A tool call is announced by `tool-input-start` and only resolved by
 * `tool-output-available` / `data-nova-tool-error`. Any frame missing between
 * them (a dropped malformed call, a policy refusal sent by an older backend, a
 * connection that died mid-tool) would otherwise leave the spinner running
 * forever, in a turn whose ESC handler is already disabled.
 */
function settleParts(parts: MessagePart[]): MessagePart[] {
    return parts.flatMap((part): MessagePart[] => {
        if (part.type === "pending") return [];
        if (part.type === "tool-call" && part.status === "running") {
            return [{ ...part, status: "error", error: UNFINISHED_TOOL_ERROR }];
        }
        return [part];
    });
}

function topSlice(state: ChatSlice): ChatSlice {
    return {
        messages: state.messages,
        sessionId: state.sessionId,
        isStreaming: state.isStreaming,
        provider: state.provider,
        model: state.model,
        reasoningEffort: state.reasoningEffort,
        agentKey: state.agentKey,
        agentName: state.agentName,
        retry: state.retry,
    };
}

function emptySlice(state: ChatSlice): ChatSlice {
    return {
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: state.provider,
        model: state.model,
        reasoningEffort: state.reasoningEffort,
        agentKey: state.agentKey,
        agentName: state.agentName,
        retry: null,
    };
}

export const useChatStore = create<ChatState>((set) => {
    /** Apply *patch* to one tab's slice, mirroring the active tab to the top level. */
    function writeSlice(
        tabId: string | null | undefined,
        patch: (slice: ChatSlice) => Partial<ChatSlice>,
    ): void {
        if (
            tabId &&
            !useTabStore.getState().tabs.some((tab) => tab.id === tabId)
        ) {
            return;
        }
        set((state) => {
            const active = useTabStore.getState().activeId;
            const key = tabId ?? active;
            if (key == null) {
                return patch(topSlice(state));
            }
            const current =
                key === active
                    ? topSlice(state)
                    : (state.byId[key] ?? emptySlice(state));
            const next: ChatSlice = { ...current, ...patch(current) };
            const byId = { ...state.byId, [key]: next };
            return key === active ? { ...next, byId } : { byId };
        });
    }

    return {
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        reasoningEffort: "",
        agentKey: DEFAULT_AGENT_KEY,
        agentName: DEFAULT_AGENT_KEY,
        retry: null,
        byId: {},

        setSessionId: (sessionId, tabId) =>
            writeSlice(tabId, () => ({ sessionId })),

        // Returning the same state keeps the clearing call from re-rendering on
        // every heartbeat-sized event.
        setRetry: (retry, tabId) =>
            writeSlice(tabId, (slice) =>
                slice.retry === null && retry === null ? {} : { retry },
            ),

        setPending: (messageId, pending, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => {
                    const hasPending = msg.parts.some(
                        (part) => part.type === "pending",
                    );
                    if (pending && !hasPending) {
                        return {
                            ...msg,
                            parts: [...msg.parts, { type: "pending" }],
                        };
                    }
                    if (!pending && hasPending) {
                        return {
                            ...msg,
                            parts: msg.parts.filter(
                                (part) => part.type !== "pending",
                            ),
                        };
                    }
                    return msg;
                }),
            })),

        addUserMessage: (text, images, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: [
                    ...slice.messages,
                    {
                        id: makeId(),
                        role: "user",
                        parts: [
                            {
                                type: "text",
                                text,
                                ...(images && images.length > 0
                                    ? { images }
                                    : {}),
                            },
                        ],
                        status: "done",
                    },
                ],
            })),

        insertWakeMessage: (text, wakeFor, variant, tabId) =>
            writeSlice(tabId, (slice) => {
                if (slice.messages.some((msg) => msg.wakeFor === wakeFor)) {
                    return {};
                }
                const message: TuiMessage = {
                    id: makeId(),
                    role: "user",
                    parts: [{ type: "text", text }],
                    status: "done",
                    wakeFor,
                    ...(variant ? { variant } : {}),
                };
                const last = slice.messages[slice.messages.length - 1];
                // The resume stream seeds its assistant placeholder first; insert the
                // wake message above it so the chip reads before its reply.
                if (last?.role === "assistant" && last.status === "streaming") {
                    return {
                        messages: [
                            ...slice.messages.slice(0, -1),
                            message,
                            last,
                        ],
                    };
                }
                return { messages: [...slice.messages, message] };
            }),

        startAssistantMessage: (tabId) => {
            const id = makeId();
            writeSlice(tabId, (slice) => ({
                isStreaming: true,
                messages: [
                    ...slice.messages,
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

        startTextPart: (messageId, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => {
                    const filtered = msg.parts.filter(
                        (part) => part.type !== "pending",
                    );
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

        appendTextDelta: (messageId, delta, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => {
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

        startReasoningPart: (messageId, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => {
                    const filtered = msg.parts.filter(
                        (part) => part.type !== "pending",
                    );
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

        appendReasoningDelta: (messageId, delta, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => {
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

        endReasoningPart: (messageId, elapsedMs, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => {
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

        startToolCall: (messageId, tool, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => ({
                    ...msg,
                    parts: [
                        ...msg.parts.filter(
                            (part) =>
                                part.type !== "pending" &&
                                (part.type !== "text" ||
                                    part.text.trim() !== ""),
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

        setToolInput: (messageId, toolCallId, input, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchToolPart(
                    slice.messages,
                    messageId,
                    toolCallId,
                    (part) => ({
                        ...part,
                        argsText: toDisplayText(input),
                        args: toArgsObject(input),
                    }),
                ),
            })),

        setToolOutput: (messageId, toolCallId, output, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchToolPart(
                    slice.messages,
                    messageId,
                    toolCallId,
                    (part) => ({
                        ...part,
                        outputText: toDisplayText(output),
                        status: "done",
                    }),
                ),
            })),

        setToolStatus: (messageId, toolCallId, status, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchToolPart(
                    slice.messages,
                    messageId,
                    toolCallId,
                    (part) => ({ ...part, status }),
                ),
            })),

        failToolCall: (messageId, toolCallId, message, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchToolPart(
                    slice.messages,
                    messageId,
                    toolCallId,
                    (part) => ({
                        ...part,
                        status: "error",
                        error: message,
                    }),
                ),
            })),

        completeStream: (tabId) =>
            writeSlice(tabId, (slice) => ({
                isStreaming: false,
                retry: null,
                messages: slice.messages.map((msg) =>
                    msg.status === "streaming"
                        ? {
                              ...msg,
                              status: "done",
                              parts: settleParts(msg.parts),
                          }
                        : msg,
                ),
            })),

        failStream: (error, tabId) =>
            writeSlice(tabId, (slice) => ({
                isStreaming: false,
                retry: null,
                messages: slice.messages.map((msg) =>
                    msg.status === "streaming"
                        ? {
                              ...msg,
                              status: "error",
                              error,
                              parts: settleParts(msg.parts),
                          }
                        : msg,
                ),
            })),

        resetAssistantMessage: (messageId, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => ({
                    ...msg,
                    status: "streaming",
                    error: undefined,
                    parts: [{ type: "pending" }],
                })),
            })),

        dropMessage: (messageId, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: slice.messages.filter((msg) => msg.id !== messageId),
            })),

        replaceMessageText: (messageId, text, tabId) =>
            writeSlice(tabId, (slice) => ({
                messages: patchMessage(slice.messages, messageId, (msg) => ({
                    ...msg,
                    parts: msg.parts.map((part) =>
                        part.type === "text" ? { ...part, text } : part,
                    ),
                })),
            })),

        dropMessagesAfter: (messageId, tabId) =>
            writeSlice(tabId, (slice) => {
                const index = slice.messages.findIndex(
                    (msg) => msg.id === messageId,
                );
                if (index < 0) return slice;
                return { ...slice, messages: slice.messages.slice(0, index + 1) };
            }),


        loadHistory: (sessionId, messages, tabId) =>
            writeSlice(tabId, () => ({
                sessionId,
                messages,
                isStreaming: false,
                retry: null,
            })),

        setRoute: (route, tabId) =>
            writeSlice(tabId, () => ({
                provider: route.provider,
                model: route.model,
                ...(route.reasoningEffort === undefined
                    ? {}
                    : { reasoningEffort: route.reasoningEffort }),
            })),

        setAgent: (agentKey, agentName, tabId) =>
            writeSlice(tabId, () => ({ agentKey, agentName })),

        clearMessages: (tabId) =>
            writeSlice(tabId, () => ({ messages: [], isStreaming: false })),

        activate: (nextId, previousId) =>
            set((state) => {
                const byId = { ...state.byId };
                if (previousId && previousId !== nextId) {
                    byId[previousId] = topSlice(state);
                }
                const next =
                    nextId != null
                        ? (byId[nextId] ?? emptySlice(state))
                        : emptySlice(state);
                return { ...next, byId };
            }),

        remove: (tabId) =>
            set((state) => {
                if (!(tabId in state.byId)) return state;
                const byId = { ...state.byId };
                delete byId[tabId];
                return { byId };
            }),

        reset: () => {
            const active = useTabStore.getState().activeId;
            set((state) => {
                const byId = { ...state.byId };
                if (active) delete byId[active];
                return {
                    messages: [],
                    sessionId: null,
                    isStreaming: false,
                    retry: null,
                    byId,
                };
            });
        },
    };
});

/** Read the latest state for stream logic (avoid closures capturing stale values) */
export const getChatState = () => useChatStore.getState();

/** Snapshot of one tab's transcript; the active tab reads through the top level. */
export function chatSlice(tabId: string | null): ChatSlice {
    const state = useChatStore.getState();
    const active = useTabStore.getState().activeId;
    if (tabId == null || tabId === active) return topSlice(state);
    return (
        state.byId[tabId] ?? {
            messages: [],
            sessionId: null,
            isStreaming: false,
            provider: state.provider,
            model: state.model,
            reasoningEffort: state.reasoningEffort,
            agentKey: state.agentKey,
            agentName: state.agentName,
            retry: null,
        }
    );
}

export function isTabStreaming(tabId: string | null): boolean {
    return chatSlice(tabId).isStreaming;
}

const EMPTY_MESSAGES: TuiMessage[] = [];

/** Reactive view of one tab's transcript, active or not. */
export function useTabMessages(tabId: string): TuiMessage[] {
    const active = useTabStore((state) => state.activeId);
    return useChatStore((state) =>
        tabId === active
            ? state.messages
            : (state.byId[tabId]?.messages ?? EMPTY_MESSAGES),
    );
}

/** Reactive view of one tab's streaming flag, active or not. */
export function useTabStreaming(tabId: string): boolean {
    const active = useTabStore((state) => state.activeId);
    return useChatStore((state) =>
        tabId === active
            ? state.isStreaming
            : (state.byId[tabId]?.isStreaming ?? false),
    );
}

/**
 * True while the tab shows the launch screen: nothing has been asked yet.
 *
 * The launch screen is not a mode the app remembers — it is what an empty
 * conversation looks like. A tab that has loaded a session, is answering, or
 * holds a message is not launching, and a tab that has none of those is. One
 * definition, so the shell and anything that asks the same question cannot
 * disagree.
 */
export const selectIsLaunching = (state: ChatState): boolean =>
    state.messages.length === 0 &&
    !state.isStreaming &&
    state.sessionId === null;
