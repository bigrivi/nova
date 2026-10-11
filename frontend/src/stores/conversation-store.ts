import type { Dispatch, SetStateAction } from "react";
import { create } from "zustand";

import type { ThreadMessageLike } from "@assistant-ui/react";

import { DRAFT_THREAD_ID } from "../lib/nova-constants";
import { nextRunningMap } from "../lib/thread-running";
import type { NovaThreadSummary } from "../types/nova";

type ThreadMessagesUpdater =
    | ThreadMessageLike[]
    | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]);

/**
 * The core conversation state: the thread list, per-thread message buffers, the
 * current/draft selection, and the per-thread running map fed by the session
 * SSE.
 *
 * This lives in a store rather than a hook's `useState` for the same reason the
 * sidecar stores do: the shell owns the sidebar and the thread viewport, so the
 * most-shared state is also the state most components need, and prop-drilling it
 * from one hook forces a fat interface and wide re-renders. A store lets each
 * view subscribe to just the slice it reads, and lets the stream controller read
 * the latest state via `getState()` instead of a captured React closure.
 */
export interface ConversationState {
    threads: NovaThreadSummary[];
    messagesByThreadId: Record<string, ThreadMessageLike[]>;
    currentThreadId: string;
    draftProjectId: string | null;
    runningByThread: Record<string, boolean>;

    setThreads: Dispatch<SetStateAction<NovaThreadSummary[]>>;
    setMessagesByThreadId: Dispatch<
        SetStateAction<Record<string, ThreadMessageLike[]>>
    >;
    setThreadMessages: (
        threadId: string,
        updater: ThreadMessagesUpdater,
    ) => void;
    setCurrentThreadId: (threadId: string) => void;
    setDraftProjectId: (projectId: string | null) => void;
    setRunningByThread: Dispatch<
        SetStateAction<Record<string, boolean>>
    >;
    setThreadRunning: (threadId: string, running: boolean) => void;
}

/** Resolve a React-style `SetStateAction` against the previous value. */
function applyAction<T>(action: SetStateAction<T>, previous: T): T {
    return typeof action === "function"
        ? (action as (prev: T) => T)(previous)
        : action;
}

export const useConversationStore = create<ConversationState>((set) => ({
    threads: [],
    messagesByThreadId: { [DRAFT_THREAD_ID]: [] },
    currentThreadId: DRAFT_THREAD_ID,
    draftProjectId: null,
    runningByThread: {},

    setThreads: (action) =>
        set((state) => ({ threads: applyAction(action, state.threads) })),
    setMessagesByThreadId: (action) =>
        set((state) => ({
            messagesByThreadId: applyAction(action, state.messagesByThreadId),
        })),
    setThreadMessages: (threadId, updater) =>
        set((state) => {
            const current = state.messagesByThreadId[threadId] || [];
            return {
                messagesByThreadId: {
                    ...state.messagesByThreadId,
                    [threadId]:
                        typeof updater === "function"
                            ? updater(current)
                            : updater,
                },
            };
        }),
    setCurrentThreadId: (threadId) => set({ currentThreadId: threadId }),
    setDraftProjectId: (projectId) => set({ draftProjectId: projectId }),
    setRunningByThread: (action) =>
        set((state) => ({
            runningByThread: applyAction(action, state.runningByThread),
        })),
    setThreadRunning: (threadId, running) =>
        set((state) => ({
            runningByThread: nextRunningMap(
                state.runningByThread,
                threadId,
                running,
            ),
        })),
}));

export const selectIsRunning = (state: ConversationState): boolean =>
    !!state.runningByThread[state.currentThreadId];

export const selectCurrentMessages = (
    state: ConversationState,
): ThreadMessageLike[] => state.messagesByThreadId[state.currentThreadId] || [];

export const selectActiveThreadListId = (
    state: ConversationState,
): string | undefined =>
    state.threads.some((thread) => thread.id === state.currentThreadId)
        ? state.currentThreadId
        : undefined;
