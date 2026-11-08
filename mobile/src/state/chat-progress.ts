/** Per-tab turn progress: approvals, questions, todos, context, compaction. */
import { create } from "zustand";

import type { ApprovalRequest, ContextUsage } from "../api/types";
import type { AskQuestion } from "../chat/ask";
import type { TodoItem } from "../chat/todo";

export type ChatProgress = {
    approval: ApprovalRequest | null;
    context: ContextUsage | null;
    requiresInput: string | null;
    ask: AskQuestion[] | null;
    todos: TodoItem[] | null;
    compacting: boolean;
    compactionSummary: string;
};

export function emptyProgress(): ChatProgress {
    return {
        approval: null,
        context: null,
        requiresInput: null,
        ask: null,
        todos: null,
        compacting: false,
        compactionSummary: "",
    };
}

/** Stable empty value so selectors do not allocate on every read. */
const EMPTY_PROGRESS: ChatProgress = emptyProgress();

type ChatProgressStore = {
    byId: Record<string, ChatProgress>;
    setApproval: (tabId: string, approval: ApprovalRequest | null) => void;
    setContext: (tabId: string, context: ContextUsage) => void;
    setRequiresInput: (tabId: string, message: string | null) => void;
    setAsk: (tabId: string, questions: AskQuestion[] | null) => void;
    setTodos: (tabId: string, todos: TodoItem[] | null) => void;
    setCompacting: (tabId: string, compacting: boolean) => void;
    appendCompaction: (tabId: string, delta: string) => void;
    /** Clear one tab before a new turn starts. */
    resetFor: (tabId: string) => void;
    remove: (tabId: string) => void;
    reset: () => void;
};

export function progressSlice(tabId: string): ChatProgress {
    return useChatProgress.getState().byId[tabId] ?? EMPTY_PROGRESS;
}

function patch(
    state: ChatProgressStore,
    tabId: string,
    updater: (current: ChatProgress) => ChatProgress,
): Pick<ChatProgressStore, "byId"> {
    const current = state.byId[tabId] ?? EMPTY_PROGRESS;
    return {
        byId: {
            ...state.byId,
            [tabId]: updater(current),
        },
    };
}

export const useChatProgress = create<ChatProgressStore>((set) => ({
    byId: {},

    setApproval: (tabId, approval) =>
        set((state) =>
            patch(state, tabId, (current) => ({
                ...current,
                approval,
                requiresInput: approval ? null : current.requiresInput,
            })),
        ),

    setContext: (tabId, context) =>
        set((state) => patch(state, tabId, (current) => ({ ...current, context }))),

    setRequiresInput: (tabId, message) =>
        set((state) =>
            patch(state, tabId, (current) => ({
                ...current,
                requiresInput: message,
            })),
        ),

    setAsk: (tabId, questions) =>
        set((state) => patch(state, tabId, (current) => ({ ...current, ask: questions }))),

    setTodos: (tabId, todos) =>
        set((state) => patch(state, tabId, (current) => ({ ...current, todos }))),

    setCompacting: (tabId, compacting) =>
        set((state) =>
            patch(state, tabId, (current) =>
                compacting
                    ? { ...current, compacting: true, compactionSummary: "" }
                    : { ...current, compacting: false },
            ),
        ),

    appendCompaction: (tabId, delta) =>
        set((state) =>
            patch(state, tabId, (current) => ({
                ...current,
                compactionSummary: current.compactionSummary + delta,
            })),
        ),

    resetFor: (tabId) =>
        set((state) => {
            if (!(tabId in state.byId)) {
                return state;
            }
            return {
                byId: { ...state.byId, [tabId]: emptyProgress() },
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
