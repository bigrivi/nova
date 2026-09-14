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
import { Thread } from "../components/assistant-ui/thread";
import { ThreadSidebar } from "../components/sidebar/thread-sidebar";
import { toolkit } from "../components/assistant-ui/toolkit";
import { Button } from "../components/ui/button";
import { TooltipProvider } from "../components/ui/tooltip";
import { toThreadMessages } from "../lib/history-messages";
import {
    createProject,
    deleteProject,
    deleteSession,
    getAgent,
    interruptChat,
    listMessages,
    listModels,
    listProjects,
    listProviders,
    listSessions,
    renameSession,
    setSessionPinned,
    setSessionProject,
    streamChat,
    updateAgent,
    updateProject,
} from "../lib/nova-api";
import { useApprovalStore } from "../stores/approval-store";
import { useAskUserStore } from "../stores/ask-user-store";
import { useReasoningStore } from "../stores/reasoning-store";
import { useTodoStore } from "../stores/todo-store";
import type {
    NovaAttachmentData,
    NovaJsonObject,
    NovaModelRecord,
    NovaProject,
    NovaProviderRecord,
    NovaSessionSummary,
    NovaThreadSummary,
} from "../types/nova";

const DRAFT_THREAD_ID = "__draft__";

function createTextMessage(
    role: "user" | "assistant",
    text: string,
    id?: string,
): ThreadMessageLike {
    return {
        id: id ?? crypto.randomUUID(),
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
        id: id ?? crypto.randomUUID(),
        role: "assistant",
        content: [],
        createdAt: new Date(),
    };
}

type AssistantPart = Exclude<ThreadMessageLike["content"], string>[number];

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

function setAssistantText(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    updater: (text: string) => string,
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];
        const textPartIndex = parts.findLastIndex(
            (part) => part.type === "text",
        );
        const currentText =
            textPartIndex >= 0 && parts[textPartIndex]?.type === "text"
                ? parts[textPartIndex].text
                : "";
        const nextText = updater(currentText);

        if (textPartIndex >= 0) {
            parts[textPartIndex] = { type: "text", text: nextText };
        } else if (nextText) {
            parts.push({ type: "text", text: nextText });
        }

        return {
            ...message,
            content: parts,
        };
    });
}

function setAssistantReasoning(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    updater: (text: string) => string,
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];

        const reasoningIndex = parts.findLastIndex(
            (part) => part.type === "reasoning",
        );
        const currentText =
            reasoningIndex >= 0 && parts[reasoningIndex]?.type === "reasoning"
                ? parts[reasoningIndex].text
                : "";
        const nextText = updater(currentText);

        if (reasoningIndex >= 0) {
            parts[reasoningIndex] = {
                ...parts[reasoningIndex],
                type: "reasoning",
                text: nextText,
            };
        } else if (nextText) {
            parts.push({ type: "reasoning", text: nextText });
        }

        return {
            ...message,
            content: parts,
        };
    });
}

function setAssistantReasoningElapsed(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    elapsedMs: number,
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];

        const reasoningIndex = parts.findLastIndex(
            (part) => part.type === "reasoning",
        );
        const reasoningPart = parts[reasoningIndex];
        if (!reasoningPart || reasoningPart.type !== "reasoning") {
            return message;
        }

        const nextReasoningPart: AssistantPart & { elapsedMs: number } = {
            ...reasoningPart,
            type: "reasoning",
            text: reasoningPart.text,
            elapsedMs,
        };
        parts[reasoningIndex] = nextReasoningPart;

        return {
            ...message,
            content: parts,
        };
    });
}

function upsertAssistantToolCall(
    messages: ThreadMessageLike[],
    assistantMessageId: string,
    payload: {
        toolCallId: string;
        toolName?: string;
        input?: NovaJsonObject;
        output?: unknown;
        isError?: boolean;
    },
) {
    return messages.map((message) => {
        if (message.id !== assistantMessageId || message.role !== "assistant") {
            return message;
        }

        const parts =
            typeof message.content === "string"
                ? message.content
                    ? [{ type: "text" as const, text: message.content }]
                    : []
                : [...message.content];
        const toolIndex = parts.findIndex(
            (part) =>
                part.type === "tool-call" &&
                part.toolCallId === payload.toolCallId,
        );

        const current =
            toolIndex >= 0 && parts[toolIndex]?.type === "tool-call"
                ? parts[toolIndex]
                : null;

        const nextPart: AssistantPart = {
            type: "tool-call",
            toolCallId: payload.toolCallId,
            toolName: payload.toolName || current?.toolName || "tool",
            args: payload.input ?? current?.args ?? {},
            argsText:
                payload.input !== undefined
                    ? JSON.stringify(payload.input)
                    : (current?.argsText ?? ""),
            ...(payload.output !== undefined
                ? { result: payload.output }
                : current?.result !== undefined
                  ? { result: current.result }
                  : {}),
            ...(payload.isError !== undefined
                ? { isError: payload.isError }
                : current?.isError !== undefined
                  ? { isError: current.isError }
                  : {}),
        };

        if (toolIndex >= 0) {
            parts[toolIndex] = nextPart;
        } else {
            parts.push(nextPart);
        }

        return {
            ...message,
            content: parts,
        };
    });
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
    const [isRunning, setIsRunning] = useState(false);
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
    const [isMemoryDialogOpen, setIsMemoryDialogOpen] = useState(false);
    const [composerText, setComposerText] = useState("");

    const composerRef = useRef<HTMLTextAreaElement | null>(null);
    const sessionIdRef = useRef(DRAFT_THREAD_ID);

    useEffect(() => {
        sessionIdRef.current = currentThreadId;
    }, [currentThreadId]);

    const currentMessages = messagesByThreadId[currentThreadId] || [];
    const activeThreadListId = threads.some(
        (thread) => thread.id === currentThreadId,
    )
        ? currentThreadId
        : undefined;

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

        void bootstrap();

        return () => {
            cancelled = true;
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
        if (isRunning) {
            return;
        }

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
        if (isRunning && threadId === currentThreadId) {
            return;
        }
        try {
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

    useEffect(() => {
        if (isRunning) {
            return;
        }

        const textarea = composerRef.current;
        if (!textarea) {
            return;
        }

        textarea.focus({ preventScroll: true });
        const caret = textarea.value.length;
        textarea.setSelectionRange(caret, caret);
    }, [currentThreadId, isRunning]);

    async function submitPrompt(
        prompt: string,
        attachments?: NovaAttachmentData[],
    ) {
        if (!prompt) {
            return;
        }

        const selectedModel =
            models.find((item) => item.id === selectedModelId) || null;
        const originThreadId = currentThreadId;
        const userMessageId = crypto.randomUUID();
        const assistantMessageId = crypto.randomUUID();
        const userMessage = {
            ...createTextMessage("user", prompt, userMessageId),
            content: buildUserMessageParts(prompt, attachments),
        };
        const assistantMessage = createAssistantMessage(assistantMessageId);
        let activeThreadId = sessionIdRef.current;
        let requiresInput = false;
        let pendingAskUser: { input: unknown } | null = null;

        setIsRunning(true);
        setComposerText("");
        useTodoStore.getState().clear();

        setThreadMessages(activeThreadId, (previous) => [
            ...buildDraftMessages(previous),
            userMessage,
            assistantMessage,
        ]);

        try {
            await streamChat({
                message: prompt,
                sessionId:
                    sessionIdRef.current === DRAFT_THREAD_ID
                        ? null
                        : sessionIdRef.current,
                provider: selectedModel?.provider || null,
                model: selectedModel?.model || null,
                projectId:
                    sessionIdRef.current === DRAFT_THREAD_ID
                        ? draftProjectId
                        : null,
                attachments,
                onEvent: (event) => {
                    if (event.type === "data-nova-session") {
                        const sessionId = String(event.data?.sessionId || "");
                        if (!sessionId) {
                            return;
                        }
                        if (sessionId === sessionIdRef.current) return;

                        sessionIdRef.current = sessionId;
                        activeThreadId = sessionId;
                        startTransition(() => {
                            setMessagesByThreadId((previous) => {
                                const sourceMessages =
                                    previous[originThreadId] || [];
                                return {
                                    ...previous,
                                    [sessionId]: sourceMessages,
                                    [DRAFT_THREAD_ID]: [],
                                };
                            });
                            setCurrentThreadId(sessionId);
                            setThreads((previous) => {
                                const existing = previous.find(
                                    (thread) => thread.id === sessionId,
                                );
                                return upsertThread(
                                    previous,
                                    existing ?? {
                                        id: sessionId,
                                        title: createOptimisticSessionTitle(
                                            prompt,
                                        ),
                                        status: "regular",
                                        workspace_dir: null,
                                        project_id: draftProjectId,
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

                    if (event.type === "text-start") {
                        setThreadMessages(activeThreadId, (previous) =>
                            previous.map((msg) => {
                                if (
                                    msg.id !== assistantMessageId ||
                                    msg.role !== "assistant"
                                )
                                    return msg;
                                const parts =
                                    typeof msg.content === "string"
                                        ? msg.content
                                            ? [
                                                  {
                                                      type: "text" as const,
                                                      text: msg.content,
                                                  },
                                              ]
                                            : []
                                        : [...msg.content];
                                parts.push({ type: "text" as const, text: "" });
                                return { ...msg, content: parts };
                            }),
                        );
                        return;
                    }

                    if (event.type === "text-delta") {
                        setThreadMessages(activeThreadId, (previous) =>
                            setAssistantText(
                                previous,
                                assistantMessageId,
                                (text) => text + (event.delta || ""),
                            ),
                        );
                        return;
                    }

                    if (event.type === "reasoning-start") {
                        setThreadMessages(activeThreadId, (previous) =>
                            previous.map((msg) => {
                                if (
                                    msg.id !== assistantMessageId ||
                                    msg.role !== "assistant"
                                )
                                    return msg;
                                const parts =
                                    typeof msg.content === "string"
                                        ? msg.content
                                            ? [
                                                  {
                                                      type: "text" as const,
                                                      text: msg.content,
                                                  },
                                              ]
                                            : []
                                        : [...msg.content];
                                parts.push({
                                    type: "reasoning" as const,
                                    text: "",
                                });
                                return { ...msg, content: parts };
                            }),
                        );
                        return;
                    }

                    if (event.type === "reasoning-delta") {
                        setThreadMessages(activeThreadId, (previous) =>
                            setAssistantReasoning(
                                previous,
                                assistantMessageId,
                                (text) => text + (event.delta || ""),
                            ),
                        );
                        return;
                    }

                    if (event.type === "reasoning-end") {
                        const elapsedMs = event.elapsedMs ?? null;
                        if (elapsedMs == null) {
                            return;
                        }
                        setThreadMessages(activeThreadId, (previous) =>
                            setAssistantReasoningElapsed(
                                previous,
                                assistantMessageId,
                                elapsedMs,
                            ),
                        );
                        return;
                    }

                    if (event.type === "tool-input-start") {
                        if (!event.toolCallId) {
                            return;
                        }
                        const toolCallId = event.toolCallId;

                        setThreadMessages(activeThreadId, (previous) =>
                            upsertAssistantToolCall(
                                previous,
                                assistantMessageId,
                                {
                                    toolCallId,
                                    toolName: event.toolName,
                                },
                            ),
                        );
                        return;
                    }

                    if (event.type === "tool-input-available") {
                        if (!event.toolCallId) {
                            return;
                        }
                        const toolCallId = event.toolCallId;

                        if (event.toolName === "ask_user") {
                            pendingAskUser = { input: event.input };
                        }

                        if (event.toolName === "todo_write") {
                            useTodoStore.getState().setActive(event.input);
                        }

                        setThreadMessages(activeThreadId, (previous) =>
                            upsertAssistantToolCall(
                                previous,
                                assistantMessageId,
                                {
                                    toolCallId,
                                    toolName: event.toolName,
                                    input: event.input,
                                },
                            ),
                        );
                        return;
                    }

                    if (event.type === "tool-output-available") {
                        if (!event.toolCallId) {
                            return;
                        }
                        const toolCallId = event.toolCallId;

                        setThreadMessages(activeThreadId, (previous) =>
                            upsertAssistantToolCall(
                                previous,
                                assistantMessageId,
                                {
                                    toolCallId,
                                    output: event.output,
                                },
                            ),
                        );
                        return;
                    }

                    if (event.type === "data-nova-tool-error") {
                        const toolCallId = String(
                            event.data?.toolCallId ?? "",
                        );
                        if (!toolCallId) {
                            return;
                        }

                        setThreadMessages(activeThreadId, (previous) =>
                            upsertAssistantToolCall(
                                previous,
                                assistantMessageId,
                                { toolCallId, isError: true },
                            ),
                        );
                        return;
                    }

                    if (event.type === "data-nova-heartbeat") {
                        return;
                    }

                    if (event.type === "data-nova-approval-required") {
                        useApprovalStore.getState().setPending({
                            sessionId: activeThreadId,
                            requestId: String(event.data?.requestId || ""),
                            command: String(event.data?.command || ""),
                            description: String(event.data?.description || ""),
                        });
                        return;
                    }

                    if (event.type === "data-nova-input-required") {
                        requiresInput = true;
                        return;
                    }

                    if (event.type === "error") {
                        throw new Error(event.errorText || "Unknown error");
                    }
                },
            });

            if (requiresInput) {
                return;
            }
        } catch (error) {
            const messageText =
                error instanceof Error ? error.message : String(error);
            setThreadMessages(activeThreadId, (previous) =>
                setAssistantText(
                    previous,
                    assistantMessageId,
                    () => `[error] ${messageText}`,
                ),
            );
        } finally {
            setIsRunning(false);

            if (requiresInput && pendingAskUser) {
                const askUser = pendingAskUser as { input: unknown };
                useAskUserStore.getState().setActive({
                    args: askUser.input,
                    argsText: JSON.stringify(askUser.input),
                    resume: (text: unknown) => {
                        submitPrompt(String(text));
                        useAskUserStore.getState().setActive(null);
                    },
                    result: null,
                    status: { type: "running" } as const,
                });
            }
        }
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
            setSelectedModelId((current) => {
                if (
                    current &&
                    nextModels.some((model) => model.id === current)
                ) {
                    return current;
                }
                return nextModels[0]?.id ?? null;
            });
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

    const handleCancel = async () => {
        useAskUserStore.getState().setActive(null);
        const sid = sessionIdRef.current;
        if (sid !== DRAFT_THREAD_ID) {
            await interruptChat(sid);
        }
    };

    const runtime = useExternalStoreRuntime({
        messages: currentMessages,
        isRunning,
        onNew: async () => {},
        onCancel: handleCancel,
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
                    if (isRunning || threadId === currentThreadId) {
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
                        <ThreadSidebar
                            threads={threads}
                            projects={projects}
                            activeThreadId={activeThreadListId}
                            runningThreadId={
                                isRunning ? activeThreadListId : undefined
                            }
                            disabled={isRunning}
                            onCollapse={() => setIsSidebarCollapsed(true)}
                            onNewThread={switchToDraftThread}
                            onNewThreadInProject={handleNewThreadInProject}
                            onCreateProject={handleCreateProject}
                            onRenameProject={handleRenameProject}
                            onDeleteProject={handleDeleteProject}
                            onSelectThread={(threadId) => {
                                if (isRunning || threadId === currentThreadId) return;
                                setCurrentThreadId(threadId);
                                void loadThread(threadId);
                            }}
                            onRenameThread={handleRenameThread}
                            onPinThread={handlePinThread}
                            onMoveThread={handleMoveThread}
                            onDeleteThread={handleDeleteThread}
                            onOpenMemory={() => setIsMemoryDialogOpen(true)}
                        />
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
                                    onCancel: handleCancel,
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
                                    providers,
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
                                    onModelsUpdated: handleConfigModelsUpdated,
                                    onProvidersRefresh: refreshProviders,
                                    onStatusChange: handleConfigStatus,
                                }}
                            />
                        </div>
                    </main>
                </div>
                <MemoryManagerDialog
                    open={isMemoryDialogOpen}
                    onOpenChange={setIsMemoryDialogOpen}
                />
            </TooltipProvider>
        </AssistantRuntimeProvider>
    );
}
