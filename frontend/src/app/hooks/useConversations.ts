import type { ThreadMessageLike } from "@assistant-ui/react";
import { startTransition, useCallback, useEffect, useRef } from "react";

import {
    clearLastSequence,
    deleteSession,
    fetchSessionContext,
    getLastSequence,
    getSessionRoute,
    getStreamStatus,
    listMessages,
    renameSession,
    setSessionPinned,
} from "../../lib/nova-api";
import { DRAFT_THREAD_ID } from "../../lib/nova-constants";
import { toThreadMessages } from "../../lib/history-messages";
import type { StreamRoute } from "../../lib/stream-controller";
import { useApprovalStore } from "../../stores/approval-store";
import { useAskUserStore } from "../../stores/ask-user-store";
import { useBackgroundTaskStore } from "../../stores/background-task-store";
import { useComposerStore } from "../../stores/composer-store";
import { useContextUsageStore } from "../../stores/context-usage-store";
import { useConversationStore } from "../../stores/conversation-store";
import { useTodoStore } from "../../stores/todo-store";
import type {
    NovaAttachmentData,
    NovaSessionRoute,
    NovaModelRecord,
    NovaThreadSummary,
} from "../../types/nova";
import { useSessionEvents } from "./useSessionEvents";
import { useStreamController } from "./useStreamController";

export interface ConversationDeps {
    models: NovaModelRecord[];
    selectedModelId: string | null;
    selectedAgentKey: string;
    syncAgentForThread: (agentKey: string | null | undefined) => void;
    /** The level that applies right now, already filtered by the model. */
    getReasoningEffort?: () => string | null;
    /** Apply a reopened session's recorded route back onto the composer. */
    applySessionRoute?: (route: NovaSessionRoute) => void;
}

export interface Conversations {
    threads: NovaThreadSummary[];
    setThreads: React.Dispatch<React.SetStateAction<NovaThreadSummary[]>>;
    currentThreadId: string;
    composerRef: React.RefObject<HTMLTextAreaElement | null>;
    submitPrompt: (
        prompt: string,
        attachments?: NovaAttachmentData[],
    ) => Promise<void>;
    handleCancel: (threadId?: string) => Promise<void>;
    setThreadMessages: (
        threadId: string,
        updater:
            | ThreadMessageLike[]
            | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]),
    ) => void;
    switchToDraftThread: (projectId?: string | null) => void;
    handleNewThreadInProject: (projectId: string) => void;
    draftProjectId: string | null;
    clearDraftProject: () => void;
    isDraftThread: boolean;
    selectThread: (threadId: string) => void;
    handlePinThread: (threadId: string, pinned: boolean) => Promise<void>;
    handleRenameThread: (threadId: string, newTitle: string) => Promise<void>;
    handleDeleteThread: (
        threadId: string,
        nextThreadId?: string | null,
        deleteMemories?: boolean,
    ) => Promise<void>;
}

/**
 * Compose the conversation core from its parts: the `conversation-store` owns
 * the thread list, message buffers, and running map; the `stream-controller`
 * owns the streaming lifecycle; `useSessionEvents` owns the SSE subscription.
 * This hook wires them to the live model/agent selection and keeps the
 * thread-list CRUD that coordinates several of those pieces at once.
 */
export function useConversations(deps: ConversationDeps): Conversations {
    const threads = useConversationStore((state) => state.threads);
    const currentThreadId = useConversationStore(
        (state) => state.currentThreadId,
    );
    const draftProjectId = useConversationStore(
        (state) => state.draftProjectId,
    );
    const runningByThread = useConversationStore(
        (state) => state.runningByThread,
    );

    const setThreads = useConversationStore((state) => state.setThreads);
    const setMessagesByThreadId = useConversationStore(
        (state) => state.setMessagesByThreadId,
    );
    const setCurrentThreadId = useConversationStore(
        (state) => state.setCurrentThreadId,
    );
    const setDraftProjectId = useConversationStore(
        (state) => state.setDraftProjectId,
    );
    const setThreadMessages = useConversationStore(
        (state) => state.setThreadMessages,
    );
    const setThreadRunning = useConversationStore(
        (state) => state.setThreadRunning,
    );

    const composerRef = useRef<HTMLTextAreaElement | null>(null);
    const sessionIdRef = useRef(DRAFT_THREAD_ID);
    const currentThreadIdRef = useRef(DRAFT_THREAD_ID);

    // Read the route lazily from the latest deps so a turn resumed off an SSE
    // frame never streams with a model/agent selection captured at mount.
    const depsRef = useRef(deps);
    useEffect(() => {
        depsRef.current = deps;
    });
    const getRoute = useCallback<() => StreamRoute>(() => {
        const current = depsRef.current;
        const selectedModel =
            current.models.find((item) => item.id === current.selectedModelId) ||
            null;
        return {
            provider: selectedModel?.provider || null,
            model: selectedModel?.model || null,
            agentKey: current.selectedAgentKey,
            reasoningEffort: current.getReasoningEffort?.() ?? null,
        };
    }, []);

    const controller = useStreamController({
        getRoute,
        currentThreadIdRef,
        sessionIdRef,
        composerRef,
    });

    useEffect(() => {
        sessionIdRef.current = currentThreadId;
        currentThreadIdRef.current = currentThreadId;
    }, [currentThreadId]);

    useEffect(() => {
        useApprovalStore.getState().syncPendingToSession(currentThreadId);
        useAskUserStore.getState().syncActiveToSession(currentThreadId);
        // The task panel reads this; tasks themselves arrive over the events
        // stream, so nothing here polls.
        useBackgroundTaskStore
            .getState()
            .setActiveSession(
                currentThreadId === DRAFT_THREAD_ID ? null : currentThreadId,
            );
    }, [currentThreadId]);

    useSessionEvents({ controller, currentThreadIdRef });

    async function loadThread(threadId: string) {
        try {
            const messages = await listMessages(threadId);
            useTodoStore.getState().clear();
            startTransition(() => {
                setCurrentThreadId(threadId);
                setMessagesByThreadId((previous) => ({
                    ...previous,
                    [threadId]: toThreadMessages(messages),
                }));
            });
            // Context usage is computed on demand; fetch it alongside history
            // so the composer pill shows immediately without waiting for a
            // stream. Failures keep whatever the pill showed before.
            void fetchSessionContext(threadId).then((usage) => {
                if (usage) {
                    useContextUsageStore
                        .getState()
                        .setForSession(threadId, usage);
                }
            });
            try {
                const status = await getStreamStatus(threadId);
                if (status.status === "done" || status.status === "idle") {
                    clearLastSequence(threadId);
                } else if (
                    status.status === "active" ||
                    status.status === "detached"
                ) {
                    const storedCursor = getLastSequence(threadId);
                    if (
                        storedCursor !== null &&
                        typeof status.last_seq === "number" &&
                        status.last_seq < storedCursor
                    ) {
                        clearLastSequence(threadId);
                    } else {
                        void controller.resume(threadId, storedCursor);
                    }
                }
            } catch {
                // Status fetch failed: history alone is the full story.
                clearLastSequence(threadId);
            }
        } catch (error) {
            console.error("Failed to load thread:", threadId, error);
        }
    }

    function switchToDraftThread(projectId: string | null = null) {
        useTodoStore.getState().clear();
        startTransition(() => {
            setCurrentThreadId(DRAFT_THREAD_ID);
            setMessagesByThreadId((previous) => ({
                ...previous,
                [DRAFT_THREAD_ID]: previous[DRAFT_THREAD_ID] || [],
            }));
        });
        useComposerStore.getState().clear();
        setDraftProjectId(projectId);
    }

    function handleNewThreadInProject(projectId: string) {
        switchToDraftThread(projectId);
    }

    function selectThread(threadId: string) {
        if (threadId === currentThreadId) {
            return;
        }
        setCurrentThreadId(threadId);
        const thread = threads.find((item) => item.id === threadId);
        deps.syncAgentForThread(thread?.agent_key);
        // Restore the model and level this conversation actually ran with, so
        // reopening it does not silently continue on whatever the agent points
        // at today. A session with no recorded route leaves the selection alone.
        void getSessionRoute(threadId).then((route) => {
            if (route) {
                deps.applySessionRoute?.(route);
            }
        });
        void loadThread(threadId);
    }

    async function handlePinThread(threadId: string, pinned: boolean) {
        if (threadId === DRAFT_THREAD_ID) {
            return;
        }
        try {
            await setSessionPinned(threadId, pinned);
            setThreads((previous) =>
                previous.map((thread) =>
                    thread.id === threadId ? { ...thread, pinned } : thread,
                ),
            );
        } catch (error) {
            console.error("Failed to pin thread:", threadId, error);
        }
    }

    async function handleRenameThread(threadId: string, newTitle: string) {
        if (threadId === DRAFT_THREAD_ID) {
            return;
        }
        const title = newTitle.trim();
        const thread = threads.find((t) => t.id === threadId);
        if (!title || !thread || title === thread.title) {
            return;
        }
        try {
            await renameSession(threadId, title);
            startTransition(() => {
                setThreads((previous) =>
                    previous.map((thread) =>
                        thread.id === threadId ? { ...thread, title } : thread,
                    ),
                );
            });
        } catch (error) {
            console.error("Failed to rename thread:", threadId, error);
        }
    }

    async function handleDeleteThread(
        threadId: string,
        nextThreadId: string | null = null,
        deleteMemories = false,
    ) {
        if (threadId === DRAFT_THREAD_ID) {
            setThreads((previous) =>
                previous.filter((thread) => thread.id !== DRAFT_THREAD_ID),
            );
            setMessagesByThreadId((previous) => ({
                ...previous,
                [DRAFT_THREAD_ID]: [],
            }));
            return;
        }
        if (runningByThread[threadId]) {
            return;
        }
        try {
            controller.abort(threadId);
            setThreadRunning(threadId, false);
            await deleteSession(threadId, deleteMemories);
            useContextUsageStore.getState().clearSession(threadId);
            startTransition(() => {
                setThreads((previous) =>
                    previous.filter((thread) => thread.id !== threadId),
                );
                setMessagesByThreadId((previous) => {
                    const next = { ...previous };
                    delete next[threadId];
                    return next;
                });
            });
            if (currentThreadId === threadId) {
                if (nextThreadId) {
                    setCurrentThreadId(nextThreadId);
                    const thread = threads.find(
                        (item) => item.id === nextThreadId,
                    );
                    deps.syncAgentForThread(thread?.agent_key);
                    void loadThread(nextThreadId);
                } else {
                    switchToDraftThread();
                }
            }
        } catch (error) {
            console.error("Failed to delete thread:", threadId, error);
        }
    }

    return {
        threads,
        setThreads,
        currentThreadId,
        isDraftThread: currentThreadId === DRAFT_THREAD_ID,
        draftProjectId,
        clearDraftProject: () => setDraftProjectId(null),
        composerRef,
        submitPrompt: controller.submit,
        handleCancel: controller.cancel,
        setThreadMessages,
        switchToDraftThread,
        handleNewThreadInProject,
        selectThread,
        handlePinThread,
        handleRenameThread,
        handleDeleteThread,
    };
}
