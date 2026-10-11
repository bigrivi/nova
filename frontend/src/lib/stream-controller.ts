import type { Dispatch, SetStateAction } from "react";

import type { ThreadMessageLike } from "@assistant-ui/react";

import type { ApprovalPending } from "../stores/approval-store";
import type { ActiveAskUser } from "../stores/ask-user-store";
import type { ContextUsage } from "../stores/context-usage-store";
import type { NovaAttachmentData, NovaThreadSummary } from "../types/nova";
import { DRAFT_THREAD_ID } from "./nova-constants";
import {
    handleStreamEvent,
    type StreamEngineDeps,
    type StreamHandlerEnv,
} from "./stream-engine";
import { appendFailureNotice, setAssistantText } from "./thread-stream";
import {
    buildDraftMessages,
    buildUserMessageParts,
    createAssistantMessage,
    createOptimisticSessionTitle,
    createTextMessage,
} from "./thread-messages";
import { upsertThread } from "./thread-summary";
import { consumeParkedTail } from "./thread-tail";
import { randomId } from "./utils";

type ThreadMessagesUpdater =
    | ThreadMessageLike[]
    | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]);

/** The model/agent route resolved from the live composer selection. */
export interface StreamRoute {
    provider: string | null;
    model: string | null;
    agentKey: string;
    reasoningEffort: string | null;
}

/**
 * Everything the controller reads or mutates, injected so the controller is
 * React-free and unit-testable: production wires store accessors, the REST
 * client, and the id refs; tests wire plain objects and spies.
 *
 * The controller reads current conversation state through `conversation.*`
 * getters (which production backs with `store.getState()`) rather than captured
 * React values, so a turn resumed from an SSE frame always sees the latest
 * selection - this is what removes the stale closure the hook used to carry.
 */
export interface StreamControllerDeps {
    /** Live mirror of the current thread id; also written by session handoff. */
    currentThreadIdRef: { current: string };
    /** Live mirror of the viewed session id; written on draft -> real handoff. */
    sessionIdRef: { current: string };
    conversation: {
        getCurrentThreadId: () => string;
        getDraftProjectId: () => string | null;
        isRunning: (threadId: string) => boolean;
        setThreadRunning: (threadId: string, running: boolean) => void;
        setThreadMessages: (
            threadId: string,
            updater: ThreadMessagesUpdater,
        ) => void;
        setMessagesByThreadId: Dispatch<
            SetStateAction<Record<string, ThreadMessageLike[]>>
        >;
        setCurrentThreadId: (threadId: string) => void;
        setThreads: Dispatch<SetStateAction<NovaThreadSummary[]>>;
    };
    getRoute: () => StreamRoute;
    api: {
        streamChat: typeof import("./nova-api").streamChat;
        getLastSequence: typeof import("./nova-api").getLastSequence;
        setLastSequence: typeof import("./nova-api").setLastSequence;
        clearLastSequence: typeof import("./nova-api").clearLastSequence;
        interruptChat: typeof import("./nova-api").interruptChat;
    };
    runTransition: (fn: () => void) => void;
    composer: { clear: () => void; focus: () => void };
    todo: {
        clear: () => void;
        markOpenCancelled: () => void;
        setActive: (input: unknown) => void;
    };
    reasoning: {
        setCompacting: (compacting: boolean) => void;
        appendCompactionDelta: (delta: string) => void;
    };
    approval: {
        setPendingForSession: (
            sessionId: string,
            pending: ApprovalPending | null,
        ) => void;
        setPending: (pending: ApprovalPending | null) => void;
        clearPendingForSession: (sessionId: string) => void;
    };
    contextUsage: {
        setForSession: (sessionId: string, usage: ContextUsage) => void;
    };
    askUser: {
        setActiveForSession: (
            sessionId: string,
            call: ActiveAskUser | null,
        ) => void;
        setActive: (call: ActiveAskUser | null) => void;
        clearActiveForSession: (sessionId: string) => void;
    };
}

/**
 * The streaming lifecycle for one client: submit a fresh turn, resume (tail) an
 * existing one, cancel, and the cross-turn coordination (abort controllers, seen
 * sequences, own-turn registry, parked tails) that keeps a local stream and the
 * server-driven SSE from racing. Pure orchestration over the injected
 * `stream-engine`.
 */
export interface StreamController {
    submit: (prompt: string, attachments?: NovaAttachmentData[]) => Promise<void>;
    resume: (threadId: string, fromSequence: number | null) => Promise<void>;
    cancel: (threadId?: string) => Promise<void>;
    /** Abort and forget a local stream, e.g. when its thread is deleted. */
    abort: (threadId: string) => void;
    /** Whether this client is currently streaming the thread itself. */
    hasLocalStream: (threadId: string) => boolean;
    /** Consume (and clear) the "this active event is our own turn" marker. */
    consumeOwnActive: (sessionId: string) => boolean;
    /** Park a tail request for the draining local stream to pick up. */
    parkTail: (sessionId: string) => void;
}

export function createStreamController(
    deps: StreamControllerDeps,
): StreamController {
    const abortControllers = new Map<string, AbortController>();
    const seenSequences = new Map<string, Set<number>>();
    const expectOwnActive = new Set<string>();
    const pendingTail = new Set<string>();

    const abortControllersRef = { current: abortControllers };
    const seenSequencesRef = { current: seenSequences };
    const expectOwnActiveRef = { current: expectOwnActive };

    function buildEngineDeps(): StreamEngineDeps {
        return {
            abortControllersRef,
            seenSequencesRef,
            expectOwnActiveRef,
            sessionIdRef: deps.sessionIdRef,
            currentThreadIdRef: deps.currentThreadIdRef,
            setThreadRunning: deps.conversation.setThreadRunning,
            setThreadMessages: deps.conversation.setThreadMessages,
            setMessagesByThreadId: deps.conversation.setMessagesByThreadId,
            setCurrentThreadId: deps.conversation.setCurrentThreadId,
            setThreads: deps.conversation.setThreads,
            runTransition: deps.runTransition,
            reasoning: deps.reasoning,
            approval: deps.approval,
            todo: { setActive: deps.todo.setActive },
            contextUsage: deps.contextUsage,
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
        reasoningEffort?: string | null;
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
        const engineDeps = buildEngineDeps();
        if (args.resumeFromSequence == null) {
            seenSequences.set(args.originThreadId, new Set<number>());
        }
        const controller = new AbortController();
        abortControllers.set(args.originThreadId, controller);
        expectOwnActive.add(args.originThreadId);
        deps.conversation.setThreadRunning(args.originThreadId, true);
        try {
            await deps.api.streamChat({
                message: args.message,
                sessionId: args.sessionId,
                provider: args.provider,
                model: args.model,
                agentKey: args.agentKey,
                reasoningEffort: args.reasoningEffort ?? null,
                projectId: args.projectId,
                attachments: args.attachments,
                signal: controller.signal,
                resumeFromSequence: args.resumeFromSequence,
                onSequence: (sequence) =>
                    deps.api.setLastSequence(env.state.activeThreadId, sequence),
                onEvent: (event) => handleStreamEvent(event, env, engineDeps),
            });
            if (!env.flags.requiresInput) {
                deps.api.clearLastSequence(env.state.activeThreadId);
            }
        } catch (error) {
            if (error instanceof Error && error.name === "AbortError") {
                return;
            }
            const messageText =
                error instanceof Error ? error.message : String(error);
            const failedThreadId = env.state.activeThreadId;
            const failedAssistantId = env.assistantMessageId;
            deps.conversation.setThreadMessages(failedThreadId, (previous) =>
                setAssistantText(previous, failedAssistantId, (text) =>
                    appendFailureNotice(text, messageText),
                ),
            );
        } finally {
            abortControllers.delete(args.originThreadId);
            abortControllers.delete(env.state.activeThreadId);
            expectOwnActive.delete(args.originThreadId);
            expectOwnActive.delete(env.state.activeThreadId);
            deps.conversation.setThreadRunning(args.originThreadId, false);
            deps.conversation.setThreadRunning(env.state.activeThreadId, false);

            // Consume a parked tail request: a server-initiated turn went
            // active while this local stream was still draining, so the
            // direct tail had to skip. Tail it now that the stream is gone.
            const finishedThreadId =
                env.state.activeThreadId || args.originThreadId;
            const tailThreadId = consumeParkedTail(
                pendingTail,
                finishedThreadId,
                finishedThreadId === deps.currentThreadIdRef.current,
            );
            if (tailThreadId !== null) {
                void resume(
                    tailThreadId,
                    deps.api.getLastSequence(tailThreadId),
                );
            }

            if (env.flags.requiresInput && env.flags.pendingAskUser) {
                const askUser = env.flags.pendingAskUser as { input: unknown };
                const resumedThreadId = env.state.activeThreadId;
                const activeCall: ActiveAskUser = {
                    args: askUser.input,
                    argsText: JSON.stringify(askUser.input),
                    resume: (text: unknown) => {
                        void submit(String(text));
                        deps.askUser.clearActiveForSession(resumedThreadId);
                        if (resumedThreadId === deps.currentThreadIdRef.current) {
                            deps.askUser.setActive(null);
                        }
                    },
                    result: null,
                    status: { type: "running" } as const,
                };
                deps.askUser.setActiveForSession(resumedThreadId, activeCall);
                if (resumedThreadId === deps.currentThreadIdRef.current) {
                    deps.askUser.setActive(activeCall);
                }
            }
        }
    }

    async function resume(threadId: string, fromSequence: number | null) {
        // Only a local stream (this client already tailing) should block a
        // resume. A thread marked running purely from the /active poll is a
        // server-initiated turn we WANT to tail, so it must not short-circuit.
        if (abortControllers.has(threadId)) {
            return;
        }
        const assistantMessageId = randomId();
        deps.conversation.setThreadMessages(threadId, (previous) => [
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

    async function submit(prompt: string, attachments?: NovaAttachmentData[]) {
        if (!prompt) {
            return;
        }
        const originThreadId = deps.conversation.getCurrentThreadId();
        if (
            deps.conversation.isRunning(originThreadId) ||
            abortControllers.has(originThreadId)
        ) {
            return;
        }

        const route = deps.getRoute();
        const userMessageId = randomId();
        const assistantMessageId = randomId();
        const userMessage = {
            ...createTextMessage("user", prompt, userMessageId),
            content: buildUserMessageParts(prompt, attachments),
        };
        const assistantMessage = createAssistantMessage(assistantMessageId);
        const sessionId = deps.sessionIdRef.current;
        const submitSessionId =
            sessionId === DRAFT_THREAD_ID ? null : sessionId;
        const submitProjectId =
            sessionId === DRAFT_THREAD_ID
                ? deps.conversation.getDraftProjectId()
                : null;

        deps.composer.clear();
        deps.composer.focus();
        deps.todo.clear();
        deps.api.clearLastSequence(originThreadId);

        deps.conversation.setThreadMessages(originThreadId, (previous) => [
            ...buildDraftMessages(previous),
            userMessage,
            assistantMessage,
        ]);

        if (submitSessionId === null) {
            // Optimistic placeholder: the real session id only arrives with
            // the first SSE frame, so list the draft immediately to avoid the
            // sidebar lagging one round-trip behind the composer.
            const optimisticTitle = createOptimisticSessionTitle(prompt);
            deps.conversation.setThreads((previous) =>
                upsertThread(
                    previous.filter((thread) => thread.id !== DRAFT_THREAD_ID),
                    {
                        id: DRAFT_THREAD_ID,
                        title: optimisticTitle,
                        status: "regular",
                        workspace_dir: null,
                        project_id: submitProjectId,
                        pinned: false,
                        updated_at: Date.now(),
                        agent_key: route.agentKey,
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
            provider: route.provider,
            model: route.model,
            agentKey: route.agentKey,
            reasoningEffort: route.reasoningEffort,
            attachments,
            resumeFromSequence: null,
        });
    }

    async function cancel(threadId?: string) {
        const target = threadId ?? deps.currentThreadIdRef.current;
        deps.askUser.clearActiveForSession(target);
        if (target === deps.currentThreadIdRef.current) {
            deps.askUser.setActive(null);
        }
        abortControllers.get(target)?.abort();
        deps.todo.markOpenCancelled();
        if (target !== DRAFT_THREAD_ID) {
            await deps.api.interruptChat(target);
        }
    }

    return {
        submit,
        resume,
        cancel,
        abort: (threadId) => {
            abortControllers.get(threadId)?.abort();
            abortControllers.delete(threadId);
        },
        hasLocalStream: (threadId) => abortControllers.has(threadId),
        consumeOwnActive: (sessionId) => expectOwnActive.delete(sessionId),
        parkTail: (sessionId) => {
            pendingTail.add(sessionId);
        },
    };
}
