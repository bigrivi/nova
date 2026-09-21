import type { ThreadMessageLike } from "@assistant-ui/react";
import { startTransition, useEffect, useRef, useState } from "react";

import {
    clearLastSequence,
    deleteSession,
    getLastSequence,
    getStreamStatus,
    interruptChat,
    listMessages,
    renameSession,
    sessionEventsUrl,
    setLastSequence,
    setSessionPinned,
    streamChat,
} from "../../lib/nova-api";
import { DRAFT_THREAD_ID } from "../../lib/nova-constants";
import { toThreadMessages } from "../../lib/history-messages";
import {
    handleStreamEvent,
    type StreamEngineDeps,
    type StreamHandlerEnv,
} from "../../lib/stream-engine";
import {
    nextRunningMap,
    reconcileRunningMap,
} from "../../lib/thread-running";
import { setAssistantText } from "../../lib/thread-stream";
import {
    buildDraftMessages,
    buildUserMessageParts,
    createAssistantMessage,
    createOptimisticSessionTitle,
    createTextMessage,
} from "../../lib/thread-messages";
import { upsertThread } from "../../lib/thread-summary";
import { randomId } from "../../lib/utils";
import { useApprovalStore } from "../../stores/approval-store";
import {
    useAskUserStore,
    type ActiveAskUser,
} from "../../stores/ask-user-store";
import { useReasoningStore } from "../../stores/reasoning-store";
import { useTodoStore } from "../../stores/todo-store";
import type {
    NovaAttachmentData,
    NovaModelRecord,
    NovaThreadSummary,
} from "../../types/nova";

export interface ConversationDeps {
    models: NovaModelRecord[];
    selectedModelId: string | null;
    selectedAgentKey: string;
    syncAgentForThread: (agentKey: string | null | undefined) => void;
}

export interface Conversations {
    threads: NovaThreadSummary[];
    setThreads: React.Dispatch<React.SetStateAction<NovaThreadSummary[]>>;
    currentThreadId: string;
    activeThreadListId: string | undefined;
    currentMessages: ThreadMessageLike[];
    isRunning: boolean;
    runningByThread: Record<string, boolean>;
    composerText: string;
    setComposerText: (text: string) => void;
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
 * The conversation core: thread list, per-thread message buffers, running-state
 * map (fed by the session SSE), the composer, and the streaming lifecycle
 * (submit, resume, cancel, session handoff). These concerns share the same
 * cross-closure refs (abort controllers, seen sequences, session/current ids),
 * so they live together to keep that coordination coherent and testable via
 * the injected `stream-engine`.
 */
export function useConversations(deps: ConversationDeps): Conversations {
    const [threads, setThreads] = useState<NovaThreadSummary[]>([]);
    const [messagesByThreadId, setMessagesByThreadId] = useState<
        Record<string, ThreadMessageLike[]>
    >({ [DRAFT_THREAD_ID]: [] });
    const [currentThreadId, setCurrentThreadId] = useState(DRAFT_THREAD_ID);
    const [draftProjectId, setDraftProjectId] = useState<string | null>(null);
    const [runningByThread, setRunningByThread] = useState<
        Record<string, boolean>
    >({});
    const [composerText, setComposerText] = useState("");

    const composerRef = useRef<HTMLTextAreaElement | null>(null);
    const sessionIdRef = useRef(DRAFT_THREAD_ID);
    const currentThreadIdRef = useRef(DRAFT_THREAD_ID);
    const abortControllersRef = useRef(new Map<string, AbortController>());
    const prevActiveSnapshotRef = useRef(new Set<string>());
    const seenSequencesRef = useRef(new Map<string, Set<number>>());

    const isRunning = !!runningByThread[currentThreadId];
    const currentMessages = messagesByThreadId[currentThreadId] || [];
    const activeThreadListId = threads.some(
        (thread) => thread.id === currentThreadId,
    )
        ? currentThreadId
        : undefined;

    function setThreadRunning(threadId: string, running: boolean) {
        setRunningByThread((previous) =>
            nextRunningMap(previous, threadId, running),
        );
    }

    function setThreadMessages(
        threadId: string,
        updater:
            | ThreadMessageLike[]
            | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]),
    ) {
        setMessagesByThreadId((previous) => {
            const current = previous[threadId] || [];
            return {
                ...previous,
                [threadId]:
                    typeof updater === "function" ? updater(current) : updater,
            };
        });
    }

    useEffect(() => {
        sessionIdRef.current = currentThreadId;
        currentThreadIdRef.current = currentThreadId;
    }, [currentThreadId]);

    useEffect(() => {
        useApprovalStore.getState().syncPendingToSession(currentThreadId);
        useAskUserStore.getState().syncActiveToSession(currentThreadId);
    }, [currentThreadId]);

    // Push, not poll: one SSE connection carries a snapshot of active sessions
    // on connect plus live active/idle deltas as the registry reports them, so
    // a sub-agent auto-wake lights its parent thread instantly. EventSource
    // auto-reconnects and re-sends the snapshot, keeping the map correct.
    useEffect(() => {
        const source = new EventSource(sessionEventsUrl());

        function applySnapshot(active: string[]) {
            const seenNow = new Set(active);
            const seenBefore = prevActiveSnapshotRef.current;
            prevActiveSnapshotRef.current = seenNow;
            setRunningByThread((previous) =>
                reconcileRunningMap(
                    previous,
                    seenNow,
                    seenBefore,
                    (threadId) => abortControllersRef.current.has(threadId),
                ),
            );
        }

        function applyDelta(sessionId: string, state: string) {
            const running = state === "active";
            const snapshot = new Set(prevActiveSnapshotRef.current);
            if (running) {
                snapshot.add(sessionId);
            } else {
                snapshot.delete(sessionId);
            }
            prevActiveSnapshotRef.current = snapshot;
            if (!running && abortControllersRef.current.has(sessionId)) {
                return;
            }
            setRunningByThread((previous) =>
                nextRunningMap(previous, sessionId, running),
            );
        }

        source.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data);
                if (payload.type === "snapshot") {
                    applySnapshot(payload.active ?? []);
                } else if (payload.type === "state") {
                    applyDelta(payload.session_id, payload.state);
                }
            } catch {
                // Malformed frame is non-fatal; the next event corrects state.
            }
        };

        // Close the stream when the page is hidden or torn down so the
        // backend is not left holding an orphaned SSE connection.
        const handlePageHide = () => source.close();
        window.addEventListener("pagehide", handlePageHide);

        return () => {
            window.removeEventListener("pagehide", handlePageHide);
            source.close();
        };
    }, []);

    useEffect(() => {
        const textarea = composerRef.current;
        if (!textarea) {
            return;
        }
        textarea.style.height = "0px";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
    }, [composerText]);

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
                        void resumeThreadStream(threadId, storedCursor);
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
        setComposerText("");
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
            abortControllersRef.current.get(threadId)?.abort();
            abortControllersRef.current.delete(threadId);
            setThreadRunning(threadId, false);
            await deleteSession(threadId, deleteMemories);
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

    function buildStreamEngineDeps(): StreamEngineDeps {
        return {
            abortControllersRef,
            seenSequencesRef,
            sessionIdRef,
            currentThreadIdRef,
            setThreadRunning,
            setThreadMessages,
            setMessagesByThreadId,
            setCurrentThreadId,
            setThreads,
            runTransition: startTransition,
            reasoning: {
                setCompacting: (compacting) =>
                    useReasoningStore.getState().setCompacting(compacting),
            },
            approval: {
                setPendingForSession: (sessionId, pending) =>
                    useApprovalStore
                        .getState()
                        .setPendingForSession(sessionId, pending),
                setPending: (pending) =>
                    useApprovalStore.getState().setPending(pending),
            },
            todo: {
                setActive: (input) => useTodoStore.getState().setActive(input),
            },
        };
    }

    async function streamThread(args: {
        originThreadId: string;
        assistantMessageId: string;
        prompt: string;
        message: string;
        sessionId: string | null;
        projectId: string | null;
        provider: string | null;
        model: string | null;
        agentKey: string | null;
        attachments?: NovaAttachmentData[];
        resumeFromSequence: number | null;
    }) {
        const env: StreamHandlerEnv = {
            originThreadId: args.originThreadId,
            prompt: args.prompt,
            draftProjectId: args.projectId,
            agentKey: args.agentKey,
            assistantMessageId: args.assistantMessageId,
            state: { activeThreadId: args.originThreadId },
            flags: { requiresInput: false, pendingAskUser: null },
        };
        const engineDeps = buildStreamEngineDeps();
        if (args.resumeFromSequence == null) {
            seenSequencesRef.current.set(args.originThreadId, new Set<number>());
        }
        const controller = new AbortController();
        abortControllersRef.current.set(args.originThreadId, controller);
        setThreadRunning(args.originThreadId, true);
        try {
            await streamChat({
                message: args.message,
                sessionId: args.sessionId,
                provider: args.provider,
                model: args.model,
                agentKey: args.agentKey,
                projectId: args.projectId,
                attachments: args.attachments,
                signal: controller.signal,
                resumeFromSequence: args.resumeFromSequence,
                onSequence: (sequence) =>
                    setLastSequence(env.state.activeThreadId, sequence),
                onEvent: (event) => handleStreamEvent(event, env, engineDeps),
            });
            if (!env.flags.requiresInput) {
                clearLastSequence(env.state.activeThreadId);
            }
        } catch (error) {
            if (error instanceof Error && error.name === "AbortError") {
                return;
            }
            const messageText =
                error instanceof Error ? error.message : String(error);
            const failedThreadId = env.state.activeThreadId;
            const failedAssistantId = env.assistantMessageId;
            setThreadMessages(failedThreadId, (previous) =>
                setAssistantText(
                    previous,
                    failedAssistantId,
                    () => `[error] ${messageText}`,
                ),
            );
        } finally {
            abortControllersRef.current.delete(args.originThreadId);
            abortControllersRef.current.delete(env.state.activeThreadId);
            setThreadRunning(args.originThreadId, false);
            setThreadRunning(env.state.activeThreadId, false);

            if (env.flags.requiresInput && env.flags.pendingAskUser) {
                const askUser = env.flags.pendingAskUser as { input: unknown };
                const resumedThreadId = env.state.activeThreadId;
                const activeCall: ActiveAskUser = {
                    args: askUser.input,
                    argsText: JSON.stringify(askUser.input),
                    resume: (text: unknown) => {
                        submitPrompt(String(text));
                        useAskUserStore
                            .getState()
                            .clearActiveForSession(resumedThreadId);
                        if (resumedThreadId === currentThreadIdRef.current) {
                            useAskUserStore.getState().setActive(null);
                        }
                    },
                    result: null,
                    status: { type: "running" } as const,
                };
                useAskUserStore
                    .getState()
                    .setActiveForSession(resumedThreadId, activeCall);
                if (resumedThreadId === currentThreadIdRef.current) {
                    useAskUserStore.getState().setActive(activeCall);
                }
            }
        }
    }

    async function resumeThreadStream(
        threadId: string,
        fromSequence: number | null,
    ) {
        // Only a local stream (this client already tailing) should block a
        // resume. A thread marked running purely from the /active poll is a
        // server-initiated turn we WANT to tail, so it must not short-circuit.
        if (abortControllersRef.current.has(threadId)) {
            return;
        }
        const assistantMessageId = randomId();
        setThreadMessages(threadId, (previous) => [
            ...previous,
            createAssistantMessage(assistantMessageId),
        ]);
        await streamThread({
            originThreadId: threadId,
            assistantMessageId,
            prompt: "",
            message: "",
            sessionId: threadId,
            projectId: null,
            provider: null,
            model: null,
            agentKey: null,
            resumeFromSequence: fromSequence ?? 0,
        });
    }

    // Auto-tail the open thread when it goes active server-side without a local
    // stream. A sub-agent completion wakes the parent with a fresh turn AFTER
    // the original SSE closed, so the /active poll flips this thread's running
    // light on; we open a resume stream to play those buffered frames live.
    useEffect(() => {
        const threadId = currentThreadId;
        if (
            threadId === DRAFT_THREAD_ID ||
            !runningByThread[threadId] ||
            abortControllersRef.current.has(threadId)
        ) {
            return;
        }
        void resumeThreadStream(threadId, getLastSequence(threadId));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentThreadId, runningByThread]);

    async function submitPrompt(
        prompt: string,
        attachments?: NovaAttachmentData[],
    ) {
        if (!prompt) {
            return;
        }
        const originThreadId = currentThreadId;
        if (
            runningByThread[originThreadId] ||
            abortControllersRef.current.has(originThreadId)
        ) {
            return;
        }

        const { models, selectedModelId, selectedAgentKey } = deps;
        const selectedModel =
            models.find((item) => item.id === selectedModelId) || null;
        const userMessageId = randomId();
        const assistantMessageId = randomId();
        const userMessage = {
            ...createTextMessage("user", prompt, userMessageId),
            content: buildUserMessageParts(prompt, attachments),
        };
        const assistantMessage = createAssistantMessage(assistantMessageId);
        const submitSessionId =
            sessionIdRef.current === DRAFT_THREAD_ID
                ? null
                : sessionIdRef.current;
        const submitProjectId =
            sessionIdRef.current === DRAFT_THREAD_ID ? draftProjectId : null;

        setComposerText("");
        composerRef.current?.focus({ preventScroll: true });
        useTodoStore.getState().clear();
        clearLastSequence(originThreadId);

        setThreadMessages(originThreadId, (previous) => [
            ...buildDraftMessages(previous),
            userMessage,
            assistantMessage,
        ]);

        if (submitSessionId === null) {
            // Optimistic placeholder: the real session id only arrives with
            // the first SSE frame, so list the draft immediately to avoid the
            // sidebar lagging one round-trip behind the composer.
            const optimisticTitle = createOptimisticSessionTitle(prompt);
            setThreads((previous) =>
                upsertThread(
                    previous.filter(
                        (thread) => thread.id !== DRAFT_THREAD_ID,
                    ),
                    {
                        id: DRAFT_THREAD_ID,
                        title: optimisticTitle,
                        status: "regular",
                        workspace_dir: null,
                        project_id: submitProjectId,
                        pinned: false,
                        updated_at: Date.now(),
                        agent_key: selectedAgentKey,
                    },
                ),
            );
        }

        await streamThread({
            originThreadId,
            assistantMessageId,
            prompt,
            message: prompt,
            sessionId: submitSessionId,
            projectId: submitProjectId,
            provider: selectedModel?.provider || null,
            model: selectedModel?.model || null,
            agentKey: selectedAgentKey,
            attachments,
            resumeFromSequence: null,
        });
    }

    const handleCancel = async (threadId?: string) => {
        const target = threadId ?? currentThreadIdRef.current;
        useAskUserStore.getState().clearActiveForSession(target);
        if (target === currentThreadIdRef.current) {
            useAskUserStore.getState().setActive(null);
        }
        abortControllersRef.current.get(target)?.abort();
        useTodoStore.getState().markOpenCancelled();
        if (target !== DRAFT_THREAD_ID) {
            await interruptChat(target);
        }
    };

    return {
        threads,
        setThreads,
        currentThreadId,
        activeThreadListId,
        currentMessages,
        isRunning,
        runningByThread,
        composerText,
        setComposerText,
        composerRef,
        submitPrompt,
        handleCancel,
        setThreadMessages,
        switchToDraftThread,
        handleNewThreadInProject,
        selectThread,
        handlePinThread,
        handleRenameThread,
        handleDeleteThread,
    };
}
