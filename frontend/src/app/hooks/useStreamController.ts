import { startTransition, useState } from "react";

import {
    clearLastSequence,
    getLastSequence,
    interruptChat,
    setLastSequence,
    streamChat,
} from "../../lib/nova-api";
import {
    createStreamController,
    type StreamController,
    type StreamRoute,
} from "../../lib/stream-controller";
import { useApprovalStore } from "../../stores/approval-store";
import { useAskUserStore } from "../../stores/ask-user-store";
import { useComposerStore } from "../../stores/composer-store";
import { useContextUsageStore } from "../../stores/context-usage-store";
import { useConversationStore } from "../../stores/conversation-store";
import { useReasoningStore } from "../../stores/reasoning-store";
import { useTodoStore } from "../../stores/todo-store";

export interface StreamControllerParams {
    /** Resolve the live model/agent route; read lazily so it is never stale. */
    getRoute: () => StreamRoute;
    currentThreadIdRef: { current: string };
    sessionIdRef: { current: string };
    composerRef: { current: HTMLTextAreaElement | null };
}

/**
 * Instantiate the stream controller once and keep it for the component's life.
 * The controller owns the cross-turn coordination maps, so it must be stable;
 * production state is read through the conversation store's `getState()` and the
 * injected refs, which is why the controller never needs to be rebuilt.
 */
export function useStreamController(
    params: StreamControllerParams,
): StreamController {
    const [controller] = useState<StreamController>(() => {
        const conversationStore = useConversationStore.getState();
        return createStreamController({
            currentThreadIdRef: params.currentThreadIdRef,
            sessionIdRef: params.sessionIdRef,
            conversation: {
                getCurrentThreadId: () =>
                    useConversationStore.getState().currentThreadId,
                getDraftProjectId: () =>
                    useConversationStore.getState().draftProjectId,
                isRunning: (threadId) =>
                    !!useConversationStore.getState().runningByThread[threadId],
                setThreadRunning: conversationStore.setThreadRunning,
                setThreadMessages: conversationStore.setThreadMessages,
                setMessagesByThreadId: conversationStore.setMessagesByThreadId,
                setCurrentThreadId: conversationStore.setCurrentThreadId,
                setThreads: conversationStore.setThreads,
            },
            getRoute: params.getRoute,
            api: {
                streamChat,
                getLastSequence,
                setLastSequence,
                clearLastSequence,
                interruptChat,
            },
            runTransition: startTransition,
            composer: {
                clear: () => useComposerStore.getState().clear(),
                focus: () =>
                    params.composerRef.current?.focus({ preventScroll: true }),
            },
            todo: {
                clear: () => useTodoStore.getState().clear(),
                markOpenCancelled: () =>
                    useTodoStore.getState().markOpenCancelled(),
                setActive: (input) => useTodoStore.getState().setActive(input),
            },
            reasoning: {
                setCompacting: (compacting) =>
                    useReasoningStore.getState().setCompacting(compacting),
                appendCompactionDelta: (delta) =>
                    useReasoningStore.getState().appendCompactionDelta(delta),
                setRetry: (retry) => useReasoningStore.getState().setRetry(retry),
            },
            approval: {
                setPendingForSession: (sessionId, pending) =>
                    useApprovalStore
                        .getState()
                        .setPendingForSession(sessionId, pending),
                setPending: (pending) =>
                    useApprovalStore.getState().setPending(pending),
                clearPendingForSession: (sessionId) =>
                    useApprovalStore
                        .getState()
                        .clearPendingForSession(sessionId),
            },
            contextUsage: {
                setForSession: (sessionId, usage) =>
                    useContextUsageStore
                        .getState()
                        .setForSession(sessionId, usage),
            },
            askUser: {
                setActiveForSession: (sessionId, call) =>
                    useAskUserStore
                        .getState()
                        .setActiveForSession(sessionId, call),
                setActive: (call) => useAskUserStore.getState().setActive(call),
                clearActiveForSession: (sessionId) =>
                    useAskUserStore
                        .getState()
                        .clearActiveForSession(sessionId),
            },
        });
    });
    return controller;
}
