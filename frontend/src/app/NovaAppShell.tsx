import {
    AssistantRuntimeProvider,
    CompositeAttachmentAdapter,
    SimpleImageAttachmentAdapter,
    SimpleTextAttachmentAdapter,
    Tools,
    useAui,
    useExternalStoreRuntime,
    type ThreadMessageLike,
} from "@assistant-ui/react";
import { ChevronRightIcon } from "lucide-react";
import { startTransition, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import i18n from "../i18n";

import { MemoryManagerDialog } from "../components/assistant-ui/memory-manager-dialog";
import { ModelsManagerDialog } from "../components/assistant-ui/models-manager-dialog";
import { LoginDialog } from "../components/auth/login-dialog";
import { Thread } from "../components/assistant-ui/thread";
import { toolkit } from "../components/assistant-ui/toolkit";
import { ThreadSidebar } from "../components/sidebar/thread-sidebar";
import { Button } from "../components/ui/button";
import { TooltipProvider } from "../components/ui/tooltip";
import { toThreadMessages } from "../lib/history-messages";
import { nextRunningMap, reconcileRunningMap } from "../lib/thread-running";
import {
    applyStreamEvent,
    describeStreamSideEffects,
    extractApprovalRequest,
    extractSessionId,
    mergeMessagesById,
    setAssistantText,
    throwStreamError,
} from "../lib/thread-stream";
import {
    clearLastSequence,
    createProject,
    deleteProject,
    deleteSession,
    getActiveStreams,
    getAgent,
    getLastSequence,
    getStreamStatus,
    interruptChat,
    listMessages,
    listModels,
    listProjects,
    listProviders,
    listSessions,
    renameSession,
    setLastSequence,
    setSessionPinned,
    setSessionProject,
    streamChat,
    updateAgent,
    updateProject,
} from "../lib/nova-api";
import { subscribeToUnauthorized } from "../lib/auth";
import { randomId } from "../lib/utils";
import { useApprovalStore } from "../stores/approval-store";
import { useAskUserStore, type ActiveAskUser } from "../stores/ask-user-store";
import { useReasoningStore } from "../stores/reasoning-store";
import { useTodoStore } from "../stores/todo-store";
import type {
    NovaAttachmentData,
    NovaModelRecord,
    NovaProject,
    NovaProviderRecord,
    NovaSessionSummary,
    NovaStreamEvent,
    NovaThreadSummary,
} from "../types/nova";

const DRAFT_THREAD_ID = "__draft__";
const NARROW_VIEWPORT_QUERY = "(max-width: 768px)";

function createTextMessage(
    role: "user" | "assistant",
    text: string,
    id?: string,
): ThreadMessageLike {
    return {
        id: id ?? randomId(),
        role,
        content: text,
        createdAt: new Date(),
    };
}

function buildUserMessageParts(
    text: string,
    attachments?: NovaAttachmentData[],
): ThreadMessageLike["content"] {
    const imageParts: { type: "image"; image: string }[] = [];
    for (const attachment of attachments ?? []) {
        for (const part of attachment.content) {
            if (part.type === "image" && typeof part.image === "string") {
                imageParts.push({ type: "image", image: part.image });
            }
        }
    }
    if (imageParts.length === 0) {
        return text;
    }
    return [...imageParts, { type: "text", text }];
}

function createAssistantMessage(id?: string): ThreadMessageLike {
    return {
        id: id ?? randomId(),
        role: "assistant",
        content: [],
        createdAt: new Date(),
    };
}

function createOptimisticSessionTitle(userMessage: string): string {
    const title = userMessage.trim();
    if (!title) {
        return i18n.t("app.newSession");
    }

    if (title.length > 50) {
        return `${title.slice(0, 47)}...`;
    }

    return title;
}

function toThreadTitle(session: NovaSessionSummary) {
    const untitled = i18n.t("app.untitledSession");
    return (session.title || untitled).trim() || untitled;
}

function toThreadSummary(session: NovaSessionSummary): NovaThreadSummary {
    return {
        id: session.id,
        title: toThreadTitle(session),
        status: "regular",
        workspace_dir: session.workspace_dir ?? null,
        pinned: session.pinned ?? false,
        updated_at: session.updated_at,
        project_id: session.project_id ?? null,
    };
}

function upsertThread(
    threads: NovaThreadSummary[],
    nextThread: NovaThreadSummary,
): NovaThreadSummary[] {
    const filtered = threads.filter((thread) => thread.id !== nextThread.id);
    return [nextThread, ...filtered];
}

type StreamFlags = {
    requiresInput: boolean;
    pendingAskUser: { input: unknown } | null;
};

type StreamHandlerEnv = {
    originThreadId: string;
    prompt: string;
    draftProjectId: string | null;
    assistantMessageId: string;
    state: { activeThreadId: string };
    flags: StreamFlags;
};

const STREAM_PATCH_TYPES = new Set([
    "text-start",
    "text-delta",
    "reasoning-start",
    "reasoning-delta",
    "reasoning-end",
    "tool-input-start",
    "tool-input-available",
    "tool-output-available",
    "data-nova-tool-error",
]);

function buildDraftMessages(previous: ThreadMessageLike[]) {
    if (
        previous.length === 1 &&
        previous[0]?.id === "welcome" &&
        previous[0]?.role === "assistant"
    ) {
        return [];
    }
    return previous;
}

export function NovaAppShell() {
    const { t } = useTranslation();
    const [threads, setThreads] = useState<NovaThreadSummary[]>([]);
    const [messagesByThreadId, setMessagesByThreadId] = useState<
        Record<string, ThreadMessageLike[]>
    >({
        [DRAFT_THREAD_ID]: [],
    });
    const [currentThreadId, setCurrentThreadId] = useState(DRAFT_THREAD_ID);
    const [projects, setProjects] = useState<NovaProject[]>([]);
    const [draftProjectId, setDraftProjectId] = useState<string | null>(null);
    const [models, setModels] = useState<NovaModelRecord[]>([]);
    const [providers, setProviders] = useState<NovaProviderRecord[]>([]);
    const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
    const [runningByThread, setRunningByThread] = useState<
        Record<string, boolean>
    >({});
    const isRunning = !!runningByThread[currentThreadId];
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(
        () => window.matchMedia(NARROW_VIEWPORT_QUERY).matches,
    );
    const [isNarrowViewport, setIsNarrowViewport] = useState(
        () => window.matchMedia(NARROW_VIEWPORT_QUERY).matches,
    );
    const [isMemoryDialogOpen, setIsMemoryDialogOpen] = useState(false);
    const [isModelsDialogOpen, setIsModelsDialogOpen] = useState(false);
    const [authRequired, setAuthRequired] = useState(false);
    const [composerText, setComposerText] = useState("");

    const composerRef = useRef<HTMLTextAreaElement | null>(null);
    const sessionIdRef = useRef(DRAFT_THREAD_ID);
    const currentThreadIdRef = useRef(DRAFT_THREAD_ID);
    const abortControllersRef = useRef(new Map<string, AbortController>());
    const prevActiveSnapshotRef = useRef(new Set<string>());
    const seenSequencesRef = useRef(new Map<string, Set<number>>());
    const wasNarrowViewportRef = useRef(isNarrowViewport);

    function setThreadRunning(threadId: string, running: boolean) {
        setRunningByThread((previous) =>
            nextRunningMap(previous, threadId, running),
        );
    }

    function getSeenSequences(threadId: string): Set<number> {
        let seen = seenSequencesRef.current.get(threadId);
        if (!seen) {
            seen = new Set<number>();
            seenSequencesRef.current.set(threadId, seen);
        }
        return seen;
    }

    useEffect(() => {
        const query = window.matchMedia(NARROW_VIEWPORT_QUERY);
        const update = () => setIsNarrowViewport(query.matches);
        update();
        query.addEventListener("change", update);
        return () => query.removeEventListener("change", update);
    }, []);

    useEffect(() => {
        if (isNarrowViewport && !wasNarrowViewportRef.current) {
            setIsSidebarCollapsed(true);
        }
        wasNarrowViewportRef.current = isNarrowViewport;
    }, [isNarrowViewport]);

    function collapseSidebarOnNarrowViewport() {
        if (isNarrowViewport) {
            setIsSidebarCollapsed(true);
        }
    }

    useEffect(() => {
        sessionIdRef.current = currentThreadId;
        currentThreadIdRef.current = currentThreadId;
    }, [currentThreadId]);

    useEffect(() => {
        useApprovalStore.getState().syncPendingToSession(currentThreadId);
        useAskUserStore.getState().syncActiveToSession(currentThreadId);
    }, [currentThreadId]);

    const currentMessages = messagesByThreadId[currentThreadId] || [];
    const activeThreadListId = threads.some(
        (thread) => thread.id === currentThreadId,
    )
        ? currentThreadId
        : undefined;

    const bootstrapRef = useRef<() => void>(() => {});

    useEffect(() => {
        let cancelled = false;

        async function bootstrap() {
            try {
                // allSettled: one failing endpoint (an older backend without
                // /api/projects, a transient error) must not blank the shell.
                const [
                    modelsResult,
                    providersResult,
                    sessionsResult,
                    projectsResult,
                ] = await Promise.allSettled([
                    listModels(),
                    listProviders(),
                    listSessions(),
                    listProjects(),
                ]);

                if (cancelled) {
                    return;
                }

                const availableModels =
                    modelsResult.status === "fulfilled" ? modelsResult.value : [];
                const availableProviders =
                    providersResult.status === "fulfilled"
                        ? providersResult.value
                        : [];
                const savedSessions =
                    sessionsResult.status === "fulfilled"
                        ? sessionsResult.value
                        : [];
                const savedProjects =
                    projectsResult.status === "fulfilled"
                        ? projectsResult.value
                        : [];
                for (const result of [
                    modelsResult,
                    providersResult,
                    sessionsResult,
                    projectsResult,
                ]) {
                    if (result.status === "rejected") {
                        console.error("Bootstrap request failed:", result.reason);
                    }
                }

                try {
                    const agent = await getAgent("main");
                    if (agent?.provider && agent?.model) {
                        const modelId = `${agent.provider}:${agent.model}`;
                        if (availableModels.some((m) => m.id === modelId)) {
                            setSelectedModelId(modelId);
                        }
                    }
                } catch {}

                startTransition(() => {
                    setModels(availableModels);
                    setProviders(availableProviders);
                    setThreads(savedSessions.map(toThreadSummary));
                    setProjects(savedProjects);
                });
            } catch (error) {
                if (!cancelled) {
                    console.error(error);
                }
            }
        }

        bootstrapRef.current = () => {
            cancelled = false;
            void bootstrap();
        };
        void bootstrap();

        return () => {
            cancelled = true;
            bootstrapRef.current = () => {};
        };
    }, []);

    useEffect(() => subscribeToUnauthorized(() => setAuthRequired(true)), []);

    useEffect(() => {
        let cancelled = false;
        let timer: ReturnType<typeof setInterval> | undefined;

        async function pollActiveStreams() {
            if (cancelled || document.visibilityState !== "visible") {
                return;
            }
            try {
                const streams = await getActiveStreams();
                if (cancelled) {
                    return;
                }
                // Reconciled lighting: the server turns indicators on (page
                // reloaded while a task runs elsewhere), and a thread that
                // disappears between two snapshots with no local stream is
                // turned off (server finished while we only watched). Local
                // streams still turn their own light off on end. A
                // just-submitted session never appeared in a snapshot, so it
                // can never be flickered off while its slot registers.
                const seenNow = new Set(
                    streams.map((stream) => stream.session_id),
                );
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
            } catch {
                // Poll failure is non-fatal; retry on the next tick.
            }
        }

        void pollActiveStreams();
        timer = setInterval(pollActiveStreams, 5000);
        const onFocus = () => {
            void pollActiveStreams();
        };
        window.addEventListener("focus", onFocus);
        return () => {
            cancelled = true;
            if (timer !== undefined) {
                clearInterval(timer);
            }
            window.removeEventListener("focus", onFocus);
        };
    }, []);

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
                if (status.status === "done") {
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
                // Unknown session stream (404): history alone is the full story.
                clearLastSequence(threadId);
            }
        } catch (error) {
            console.error("Failed to load thread:", threadId, error);
        }
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

    async function handleCreateProject(
        name: string,
        path: string | null = null,
    ): Promise<NovaProject | null> {
        try {
            const project = await createProject(name, path);
            setProjects((previous) => [project, ...previous]);
            return project;
        } catch (error) {
            console.error("Failed to create project:", error);
            return null;
        }
    }

    async function handleRenameProject(projectId: string, name: string) {
        try {
            const project = await updateProject(projectId, { name });
            setProjects((previous) =>
                previous.map((item) => (item.id === projectId ? project : item)),
            );
        } catch (error) {
            console.error("Failed to rename project:", projectId, error);
        }
    }

    async function handleDeleteProject(projectId: string) {
        try {
            await deleteProject(projectId);
            setProjects((previous) =>
                previous.filter((item) => item.id !== projectId),
            );
            setThreads((previous) =>
                previous.map((thread) =>
                    thread.project_id === projectId
                        ? { ...thread, project_id: null }
                        : thread,
                ),
            );
        } catch (error) {
            console.error("Failed to delete project:", projectId, error);
        }
    }

    async function handleMoveThread(
        threadId: string,
        projectId: string | null,
    ) {
        try {
            await setSessionProject(threadId, projectId);
            setThreads((previous) =>
                previous.map((thread) =>
                    thread.id === threadId
                        ? { ...thread, project_id: projectId }
                        : thread,
                ),
            );
        } catch (error) {
            console.error("Failed to move thread:", threadId, error);
        }
    }

    async function handlePinThread(threadId: string, pinned: boolean) {
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
                    void loadThread(nextThreadId);
                } else {
                    switchToDraftThread();
                }
            }
        } catch (error) {
            console.error("Failed to delete thread:", threadId, error);
        }
    }

    useEffect(() => {
        const textarea = composerRef.current;
        if (!textarea) {
            return;
        }

        textarea.style.height = "0px";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
    }, [composerText]);


    function handleStreamEvent(event: NovaStreamEvent, env: StreamHandlerEnv) {
        const threadId = env.state.activeThreadId;
        const sequence = event.sequence;
        if (sequence != null) {
            const seen = getSeenSequences(threadId);
            if (seen.has(sequence)) {
                return;
            }
            seen.add(sequence);
        }

        if (event.type === "data-nova-session") {
            const sessionId = extractSessionId(event);
            if (!sessionId || sessionId === env.state.activeThreadId) {
                return;
            }
            const previousThreadId = env.state.activeThreadId;
            env.state.activeThreadId = sessionId;
            const controller = abortControllersRef.current.get(previousThreadId);
            if (controller) {
                abortControllersRef.current.delete(previousThreadId);
                abortControllersRef.current.set(sessionId, controller);
            }
            const seen = seenSequencesRef.current.get(previousThreadId);
            if (seen) {
                seenSequencesRef.current.delete(previousThreadId);
                seenSequencesRef.current.set(sessionId, seen);
            }
            setThreadRunning(previousThreadId, false);
            setThreadRunning(sessionId, true);
            const takeOver = sessionIdRef.current === previousThreadId;
            startTransition(() => {
                setMessagesByThreadId((previous) => {
                    const sourceMessages = previous[previousThreadId] || [];
                    const existing = previous[sessionId] || [];
                    const next = {
                        ...previous,
                        [sessionId]: mergeMessagesById(
                            existing,
                            sourceMessages,
                        ),
                    };
                    if (previousThreadId === DRAFT_THREAD_ID) {
                        next[DRAFT_THREAD_ID] = [];
                    }
                    return next;
                });
                if (takeOver) {
                    sessionIdRef.current = sessionId;
                    setCurrentThreadId(sessionId);
                }
                setThreads((previous) => {
                    const existing = previous.find(
                        (thread) => thread.id === sessionId,
                    );
                    return upsertThread(
                        previous,
                        existing ?? {
                            id: sessionId,
                            title: createOptimisticSessionTitle(env.prompt),
                            status: "regular",
                            workspace_dir: null,
                            project_id: env.draftProjectId,
                            pinned: false,
                            updated_at: Date.now(),
                        },
                    );
                });
            });
            return;
        }

        if (event.type === "data-nova-compaction-start") {
            useReasoningStore.getState().setCompacting(true);
            return;
        }

        if (event.type === "data-nova-compaction-end") {
            useReasoningStore.getState().setCompacting(false);
            return;
        }

        if (event.type === "data-nova-heartbeat") {
            return;
        }

        if (event.type === "data-nova-approval-required") {
            const pending = {
                sessionId: threadId,
                ...extractApprovalRequest(event),
            };
            useApprovalStore.getState().setPendingForSession(threadId, pending);
            if (threadId === currentThreadIdRef.current) {
                useApprovalStore.getState().setPending(pending);
            }
            return;
        }

        if (event.type === "data-nova-input-required") {
            env.flags.requiresInput = true;
            return;
        }

        if (event.type === "error") {
            throwStreamError(event);
        }

        if (event.type === "tool-input-available") {
            for (const sideEffect of describeStreamSideEffects(event)) {
                if (sideEffect.kind === "ask-user") {
                    env.flags.pendingAskUser = { input: sideEffect.input };
                } else {
                    useTodoStore.getState().setActive(sideEffect.input);
                }
            }
        }

        if (STREAM_PATCH_TYPES.has(event.type)) {
            const target = env.state.activeThreadId;
            const assistantMessageId = env.assistantMessageId;
            setThreadMessages(target, (previous) =>
                applyStreamEvent(previous, event, { assistantMessageId }),
            );
        }
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
        attachments?: NovaAttachmentData[];
        resumeFromSequence: number | null;
    }) {
        const env: StreamHandlerEnv = {
            originThreadId: args.originThreadId,
            prompt: args.prompt,
            draftProjectId: args.projectId,
            assistantMessageId: args.assistantMessageId,
            state: { activeThreadId: args.originThreadId },
            flags: { requiresInput: false, pendingAskUser: null },
        };
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
                projectId: args.projectId,
                attachments: args.attachments,
                signal: controller.signal,
                resumeFromSequence: args.resumeFromSequence,
                onSequence: (sequence) =>
                    setLastSequence(env.state.activeThreadId, sequence),
                onEvent: (event) => handleStreamEvent(event, env),
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
                const askUser = env.flags.pendingAskUser as {
                    input: unknown;
                };
                const resumedThreadId = env.state.activeThreadId;
                const activeCall: ActiveAskUser = {
                    args: askUser.input,
                    argsText: JSON.stringify(askUser.input),
                    resume: (text: unknown) => {
                        submitPrompt(String(text));
                        useAskUserStore
                            .getState()
                            .clearActiveForSession(resumedThreadId);
                        if (
                            resumedThreadId === currentThreadIdRef.current
                        ) {
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

    async function resumeThreadStream(threadId: string, fromSequence: number | null) {
        if (
            runningByThread[threadId] ||
            abortControllersRef.current.has(threadId)
        ) {
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
            resumeFromSequence: fromSequence ?? 0,
        });
    }

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

        await streamThread({
            originThreadId,
            assistantMessageId,
            prompt,
            message: prompt,
            sessionId: submitSessionId,
            projectId: submitProjectId,
            provider: selectedModel?.provider || null,
            model: selectedModel?.model || null,
            attachments,
            resumeFromSequence: null,
        });
    }

    async function handleComposerSubmit() {
        const prompt = composerText.trim();
        if (!prompt || isRunning) {
            return;
        }
        const composerState = runtime.thread.composer.getState();
        const pendingAttachments = composerState.attachments;

        let processedAttachments: NovaAttachmentData[] | undefined;
        if (pendingAttachments.length > 0) {
            const adapter = new CompositeAttachmentAdapter([
                new SimpleImageAttachmentAdapter(),
                new SimpleTextAttachmentAdapter(),
            ]);
            processedAttachments = [];
            for (const att of pendingAttachments) {
                if (att.status.type === "complete" && att.content) {
                    processedAttachments.push(att as NovaAttachmentData);
                } else if (att.status.type === "requires-action" && att.file) {
                    const result = await adapter.send(att as any);
                    processedAttachments.push(result as NovaAttachmentData);
                }
            }
            runtime.thread.composer.clearAttachments();
        }

        await submitPrompt(prompt, processedAttachments);
    }

    function handleConfigModelsUpdated(nextModels: NovaModelRecord[]) {
        startTransition(() => {
            setModels(nextModels);
            if (
                selectedModelId &&
                nextModels.some((model) => model.id === selectedModelId)
            ) {
                return;
            }
            const fallback = nextModels[0] ?? null;
            setSelectedModelId(fallback?.id ?? null);
            if (fallback?.provider && fallback?.model) {
                updateAgent("main", {
                    provider: fallback.provider,
                    model: fallback.model,
                }).catch(() => {});
            }
        });
    }

    async function refreshProviders() {
        const nextProviders = await listProviders();
        startTransition(() => {
            setProviders(nextProviders);
        });
    }

    function handleConfigStatus(message: string | null) {
        console.debug(message);
    }

    const handleCancel = async (threadId?: string) => {
        const target = threadId ?? currentThreadIdRef.current;
        useAskUserStore.getState().clearActiveForSession(target);
        if (target === currentThreadIdRef.current) {
            useAskUserStore.getState().setActive(null);
        }
        abortControllersRef.current.get(target)?.abort();
        if (target !== DRAFT_THREAD_ID) {
            await interruptChat(target);
        }
    };

    const runtime = useExternalStoreRuntime({
        messages: currentMessages,
        isRunning,
        onNew: async () => {},
        onCancel: () => handleCancel(),
        convertMessage: (message) => message,
        setMessages: (messages) => {
            setThreadMessages(currentThreadId, [...messages]);
        },
        onResumeToolCall: (options) => {
            void submitPrompt(String(options.payload ?? ""));
        },
        adapters: {
            attachments: new CompositeAttachmentAdapter([
                new SimpleImageAttachmentAdapter(),
                new SimpleTextAttachmentAdapter(),
            ]),
            threadList: {
                threadId: activeThreadListId,
                threads,
                archivedThreads: [],
                onSwitchToNewThread: switchToDraftThread,
                onSwitchToThread: (threadId) => {
                    if (threadId === currentThreadId) {
                        return;
                    }
                    setCurrentThreadId(threadId);
                    void loadThread(threadId);
                },
                onRename: (threadId, newTitle) =>
                    handleRenameThread(threadId, newTitle),
                onDelete: (threadId) => handleDeleteThread(threadId),
            },
        },
    });

    const aui = useAui({ tools: Tools({ toolkit }) });

    return (
        <AssistantRuntimeProvider aui={aui} runtime={runtime}>
            <TooltipProvider>
                <div className="flex h-screen overflow-hidden bg-background text-foreground">
                    {!isSidebarCollapsed ? (
                        <>
                            <div
                                className="fixed inset-0 z-40 bg-black/30 md:hidden"
                                onClick={() => setIsSidebarCollapsed(true)}
                                aria-hidden="true"
                            />
                            <div className="fixed top-0 left-0 z-40 h-full shadow-2xl md:contents md:shadow-none">
                                <ThreadSidebar
                            threads={threads}
                            projects={projects}
                            activeThreadId={activeThreadListId}
                            runningThreadId={
                                isRunning ? activeThreadListId : undefined
                            }
                            disabled={false}
                            onCollapse={() => setIsSidebarCollapsed(true)}
                            onNewThread={() => {
                                switchToDraftThread();
                                collapseSidebarOnNarrowViewport();
                            }}
                            onNewThreadInProject={(projectId) => {
                                handleNewThreadInProject(projectId);
                                collapseSidebarOnNarrowViewport();
                            }}
                            onCreateProject={handleCreateProject}
                            onRenameProject={handleRenameProject}
                            onDeleteProject={handleDeleteProject}
                            onSelectThread={(threadId) => {
                                if (threadId === currentThreadId) return;
                                setCurrentThreadId(threadId);
                                void loadThread(threadId);
                                collapseSidebarOnNarrowViewport();
                            }}
                            onRenameThread={handleRenameThread}
                            onPinThread={handlePinThread}
                            onMoveThread={handleMoveThread}
                            onDeleteThread={handleDeleteThread}
                            onOpenMemory={() => setIsMemoryDialogOpen(true)}
                            onOpenModels={() => setIsModelsDialogOpen(true)}
                                />
                            </div>
                        </>
                    ) : null}

                    <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
                        {isSidebarCollapsed ? <Button
                            type="button"
                            variant="outline"
                            size="icon"
                            className="fixed left-4 top-4 z-30 rounded-full border border-[#E4E3DF] bg-white shadow-[0_8px_24px_rgba(20,20,18,0.07)]"
                            aria-label={t("app.expandSidebar")}
                            onClick={() => setIsSidebarCollapsed(false)}
                        >
                            <ChevronRightIcon className="size-4" />
                        </Button> : null}

                        <div className="flex min-h-0 flex-1 flex-col">
                            <Thread
                                composer={{
                                    ref: composerRef,
                                    text: composerText,
                                    isRunning,
                                    onChange: setComposerText,
                                    onSubmit: () => {
                                        void handleComposerSubmit();
                                    },
                                    onCancel: () => {
                                        void handleCancel();
                                    },
                                    onKeyDown: (event) => {
                                        if (
                                            event.key === "Enter" &&
                                            !event.shiftKey
                                        ) {
                                            event.preventDefault();
                                            void handleComposerSubmit();
                                        }
                                    },
                                }}
                                modelSelection={{
                                    models,
                                    selectedModelId,
                                    onSelect: (value) => {
                                        setSelectedModelId(value);
                                        const [provider, model] =
                                            value.split(":");
                                        if (provider && model) {
                                            updateAgent("main", {
                                                provider,
                                                model,
                                            }).catch(() => {});
                                        }
                                    },
                                }}
                            />
                        </div>
                    </main>
                </div>
                <MemoryManagerDialog
                    open={isMemoryDialogOpen}
                    onOpenChange={setIsMemoryDialogOpen}
                />
                <ModelsManagerDialog
                    open={isModelsDialogOpen}
                    onOpenChange={setIsModelsDialogOpen}
                    providers={providers}
                    models={models}
                    onModelsUpdated={handleConfigModelsUpdated}
                    onProvidersRefresh={refreshProviders}
                    onStatusChange={handleConfigStatus}
                />
                <LoginDialog
                    open={authRequired}
                    onAuthenticated={() => {
                        setAuthRequired(false);
                        bootstrapRef.current();
                    }}
                />
            </TooltipProvider>
        </AssistantRuntimeProvider>
    );
}
