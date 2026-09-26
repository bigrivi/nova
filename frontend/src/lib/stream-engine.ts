import type { ThreadMessageLike } from "@assistant-ui/react";

import type { NovaStreamEvent } from "../types/nova";
import { DEFAULT_AGENT_KEY, DRAFT_THREAD_ID } from "./nova-constants";
import { createOptimisticSessionTitle } from "./thread-messages";
import { upsertThread } from "./thread-summary";
import {
    applyStreamEvent,
    describeStreamSideEffects,
    extractApprovalRequest,
    extractSessionId,
    mergeMessagesById,
    throwStreamError,
} from "./thread-stream";

export type StreamFlags = {
    requiresInput: boolean;
    pendingAskUser: { input: unknown } | null;
};

export type StreamHandlerEnv = {
    originThreadId: string;
    prompt: string;
    draftProjectId: string | null;
    agentKey: string | null;
    assistantMessageId: string;
    state: { activeThreadId: string };
    flags: StreamFlags;
};

/**
 * Event types that mutate the visible assistant message. Everything else is a
 * control frame (session handoff, compaction, approval, heartbeat, input gate).
 */
export const STREAM_PATCH_TYPES = new Set([
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

type Ref<T> = { current: T };

type ThreadMessagesUpdater =
    | ThreadMessageLike[]
    | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]);

type MessagesByThreadUpdater = (
    previous: Record<string, ThreadMessageLike[]>,
) => Record<string, ThreadMessageLike[]>;

type ThreadsUpdater = (
    previous: import("../types/nova").NovaThreadSummary[],
) => import("../types/nova").NovaThreadSummary[];

/**
 * External state the stream engine reads and mutates. Injecting these keeps the
 * engine React-free and unit-testable: production wires React refs and setters,
 * tests wire plain objects and spies.
 */
export interface StreamEngineDeps {
    abortControllersRef: Ref<Map<string, AbortController>>;
    seenSequencesRef: Ref<Map<string, Set<number>>>;
    expectOwnActiveRef: Ref<Set<string>>;
    sessionIdRef: Ref<string>;
    currentThreadIdRef: Ref<string>;
    setThreadRunning: (threadId: string, running: boolean) => void;
    setThreadMessages: (
        threadId: string,
        updater: ThreadMessagesUpdater,
    ) => void;
    setMessagesByThreadId: (updater: MessagesByThreadUpdater) => void;
    setCurrentThreadId: (threadId: string) => void;
    setThreads: (updater: ThreadsUpdater) => void;
    runTransition: (fn: () => void) => void;
    reasoning: {
        setCompacting: (compacting: boolean) => void;
        appendCompactionDelta: (delta: string) => void;
    };
    approval: {
        setPendingForSession: (
            sessionId: string,
            pending: {
                sessionId: string;
                requestId: string;
                command: string;
                description: string;
            } | null,
        ) => void;
        setPending: (
            pending: {
                sessionId: string;
                requestId: string;
                command: string;
                description: string;
            } | null,
        ) => void;
    };
    todo: { setActive: (input: unknown) => void };
}

function getSeenSequences(
    seenSequencesRef: Ref<Map<string, Set<number>>>,
    threadId: string,
): Set<number> {
    let seen = seenSequencesRef.current.get(threadId);
    if (!seen) {
        seen = new Set<number>();
        seenSequencesRef.current.set(threadId, seen);
    }
    return seen;
}

/**
 * Migrate a draft/optimistic thread onto the real server session id: move the
 * abort controller and seen-sequence set, light the running flag on the new id,
 * merge buffered messages, take over the current view when the user is still on
 * the origin thread, and upsert the thread into the list.
 */
function handleSessionHandoff(
    event: NovaStreamEvent,
    env: StreamHandlerEnv,
    deps: StreamEngineDeps,
): void {
    const sessionId = extractSessionId(event);
    if (!sessionId || sessionId === env.state.activeThreadId) {
        return;
    }
    const previousThreadId = env.state.activeThreadId;
    env.state.activeThreadId = sessionId;

    const controller = deps.abortControllersRef.current.get(previousThreadId);
    if (controller) {
        deps.abortControllersRef.current.delete(previousThreadId);
        deps.abortControllersRef.current.set(sessionId, controller);
    }
    if (deps.expectOwnActiveRef.current.delete(previousThreadId)) {
        deps.expectOwnActiveRef.current.add(sessionId);
    }
    const seen = deps.seenSequencesRef.current.get(previousThreadId);
    if (seen) {
        deps.seenSequencesRef.current.delete(previousThreadId);
        deps.seenSequencesRef.current.set(sessionId, seen);
    }
    deps.setThreadRunning(previousThreadId, false);
    deps.setThreadRunning(sessionId, true);

    const takeOver = deps.sessionIdRef.current === previousThreadId;
    deps.runTransition(() => {
        deps.setMessagesByThreadId((previous) => {
            const sourceMessages = previous[previousThreadId] || [];
            const existing = previous[sessionId] || [];
            const next = {
                ...previous,
                [sessionId]: mergeMessagesById(existing, sourceMessages),
            };
            if (previousThreadId === DRAFT_THREAD_ID) {
                next[DRAFT_THREAD_ID] = [];
            }
            return next;
        });
        if (takeOver) {
            deps.sessionIdRef.current = sessionId;
            deps.setCurrentThreadId(sessionId);
        }
        deps.setThreads((previous) => {
            const withoutDraft =
                previousThreadId === DRAFT_THREAD_ID
                    ? previous.filter((thread) => thread.id !== DRAFT_THREAD_ID)
                    : previous;
            const existing = withoutDraft.find(
                (thread) => thread.id === sessionId,
            );
            return upsertThread(
                withoutDraft,
                existing ?? {
                    id: sessionId,
                    title: createOptimisticSessionTitle(env.prompt),
                    status: "regular",
                    workspace_dir: null,
                    project_id: env.draftProjectId,
                    pinned: false,
                    updated_at: Date.now(),
                    agent_key: env.agentKey ?? DEFAULT_AGENT_KEY,
                },
            );
        });
    });
}

/**
 * Control-frame handlers that fully consume an event (no message patch). Adding
 * a new control frame means registering a handler here, not editing a branch
 * chain (open for extension, closed for modification).
 */
const TERMINAL_HANDLERS: Record<
    string,
    (event: NovaStreamEvent, env: StreamHandlerEnv, deps: StreamEngineDeps) => void
> = {
    "data-nova-session": handleSessionHandoff,
    "data-nova-compaction-start": (_event, _env, deps) =>
        deps.reasoning.setCompacting(true),
    "data-nova-compaction-delta": (event, _env, deps) =>
        deps.reasoning.appendCompactionDelta(String(event.data?.delta || "")),
    "data-nova-compaction-end": (_event, _env, deps) =>
        deps.reasoning.setCompacting(false),
    "data-nova-heartbeat": () => {},
    "data-nova-approval-required": (event, env, deps) => {
        const threadId = env.state.activeThreadId;
        const pending = {
            sessionId: threadId,
            ...extractApprovalRequest(event),
        };
        deps.approval.setPendingForSession(threadId, pending);
        if (threadId === deps.currentThreadIdRef.current) {
            deps.approval.setPending(pending);
        }
    },
    "data-nova-input-required": (_event, env) => {
        env.flags.requiresInput = true;
    },
};

/**
 * Route one stream event: dedupe by sequence, dispatch control frames through
 * the terminal handler table, capture ask-user/todo side effects, then apply
 * message patches. Behaviour matches the original inline handler exactly.
 */
export function handleStreamEvent(
    event: NovaStreamEvent,
    env: StreamHandlerEnv,
    deps: StreamEngineDeps,
): void {
    const threadId = env.state.activeThreadId;
    const sequence = event.sequence;
    if (sequence != null) {
        const seen = getSeenSequences(deps.seenSequencesRef, threadId);
        if (seen.has(sequence)) {
            return;
        }
        seen.add(sequence);
    }

    const terminal = TERMINAL_HANDLERS[event.type];
    if (terminal) {
        terminal(event, env, deps);
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
                deps.todo.setActive(sideEffect.input);
            }
        }
    }

    if (STREAM_PATCH_TYPES.has(event.type)) {
        const target = env.state.activeThreadId;
        const assistantMessageId = env.assistantMessageId;
        deps.setThreadMessages(target, (previous) =>
            applyStreamEvent(previous, event, { assistantMessageId }),
        );
    }
}
