/** Chat stream processing state machine: SSE events → store updates (pure logic, no UI dependencies)
 *
 * Event protocol per nova/server/ai_sdk_stream.py + frontend/src/app/NovaAppShell.tsx:
 * - data-nova-session       first-session creation, records the sessionId, reused by later messages
 * - text-* / reasoning-*    text and reasoning streams
 * - tool-input-* / tool-output-available / data-nova-tool-error   tool calls
 * - data-nova-approval-required  command approval pending → approval store
 * - data-nova-input-required     ask_user pending → activate the ask-user form
 * - data-nova-context            context window usage → ctx store
 * - data-nova-compaction-*       history compaction in progress → compaction store
 * - abort / finish / error  finalization
 */
import { resolveProject, streamChat } from "../api/nova-api.ts";
import {
    applyStreamEvent,
    type StreamAccumulator,
    type StreamEffects,
} from "./apply-event.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore, type AskQuestion } from "../stores/ask-user-store.ts";
import { getChatState } from "../stores/chat-store.ts";
import type { NovaAttachmentData } from "../api/types.ts";
import { useCompactionStore } from "../stores/compaction-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import {
    parseTodos,
    useTodoStore,
} from "../stores/todo-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

export type ChatRunOptions = {
    message: string;
    /** What the transcript shows; defaults to `message`. */
    displayText?: string;
    /** Images pasted into the composer; the backend folds them into the turn. */
    attachments?: NovaAttachmentData[];
};

/** The TUI keeps one working directory for its lifetime, so resolve it once. */
let resolvedProject: { path: string; id: string } | null = null;

async function projectIdForPath(path: string): Promise<string | null> {
    if (resolvedProject?.path === path) {
        return resolvedProject.id;
    }
    const project = await resolveProject(path);
    if (!project) {
        return null;
    }
    resolvedProject = { path, id: project.id };
    return project.id;
}

/** Monotonic id per runChatStream call: lets stream teardown clear only the
approval its own run created, never a newer live one from a later run. */
let runCounter = 0;

/** Session ids whose next `state: active` event is this client's own turn. */
const expectOwnActive = new Set<string>();
/** Active events that arrived while a local stream was still draining. */
const pendingTail = new Set<string>();

/** Consume the "this active event is our own turn" marker. */
export function consumeOwnActive(sessionId: string): boolean {
    return expectOwnActive.delete(sessionId);
}

/** Park a wake request for the draining stream's cleanup to tail. */
export function parkTail(sessionId: string): void {
    pendingTail.add(sessionId);
}

/** Drop a pending approval created by *this* run when its stream ends with
the dialog still showing: the backend unregisters in its finally, so the
dialog is unresolvable (any later y → 404). Notify on abnormal end only. */
function clearStaleApproval(runId: number, notify: boolean): void {
    const pending = useApprovalStore.getState().pending;
    if (pending && pending.runId === runId) {
        useApprovalStore.getState().setPending(null);
        if (notify) {
            useToastStore
                .getState()
                .show("Approval expired: the request ended before it was answered.", 4000);
        }
    }
}


/** Answer format: matches the frontend handleSubmit (Q/A lines, submitted as a new message) */
/** Submit ask_user answers: clears the active form and starts a new stream */
export async function submitAskAnswers(
    questions: import("../stores/ask-user-store.ts").AskQuestion[],
    answers: Record<string, string>,
): Promise<void> {
    useAskUserStore.getState().setActive(null);
    const text = formatAskAnswers(questions, answers);
    if (text) {
        await runChatStream({ message: text });
    }
}

/** Cancel the active ask_user form and report cancellation to the model */
export async function submitAskCancel(
    questions: import("../stores/ask-user-store.ts").AskQuestion[],
): Promise<void> {
    useAskUserStore.getState().setActive(null);
    const skipped = questions
        .map((q) => `Q (${q.id}): [cancelled by user]`)
        .join("\n");
    await runChatStream({ message: skipped || "[cancelled by user]" });
}

export function formatAskAnswers(
    questions: AskQuestion[],
    answers: Record<string, string>,
): string {
    const lines: string[] = [];
    for (const q of questions) {
        lines.push(`Q (${q.id}): ${q.question}`);
        lines.push(`A: ${answers[q.id] ?? ""}`);
        lines.push("");
    }
    return lines.join("\n").trim();
}

/** Run one user-initiated conversation round. */
export async function runChatStream(options: ChatRunOptions): Promise<void> {
    await runTurn({
        message: options.message,
        displayText: options.displayText,
        attachments: options.attachments,
    });
}

/**
 * Tail a server-initiated turn without sending a message.
 *
 * A background task completion wakes its session with a headless turn after the
 * original SSE closed. Reattaching with a sequence cursor replays that turn and
 * follows it live, so the wake message and reply appear in place.
 */
export async function resumeChatStream(sessionId: string): Promise<void> {
    if (getChatState().isStreaming) {
        parkTail(sessionId);
        return;
    }
    if (getChatState().sessionId !== sessionId) {
        return;
    }
    await runTurn({
        message: "",
        resumeSessionId: sessionId,
        resumeFromSequence: 0,
    });
}

type TurnOptions = {
    message: string;
    displayText?: string;
    attachments?: NovaAttachmentData[];
    /** Set when tailing an existing turn instead of starting a new one. */
    resumeSessionId?: string;
    /** Sequence cursor; null/undefined starts a fresh turn. */
    resumeFromSequence?: number | null;
};

/** Run one conversation round: optimistically insert the message → consume the stream → finalize the state machine. */
async function runTurn(options: TurnOptions): Promise<void> {
    const store = getChatState();
    const sessionId = options.resumeSessionId ?? store.sessionId;
    const { provider, model, agentKey, reasoningEffort } = store;
    const runId = ++runCounter;
    const resuming = options.resumeFromSequence != null;

    if (!resuming) {
        store.addUserMessage(
            // The `Attached file:` lines are for the model; the bubble shows
            // what the user actually typed.
            options.displayText ?? options.message,
            options.attachments?.map((attachment) => attachment.name),
        );
    }
    const assistantId = store.startAssistantMessage();
    if (sessionId) {
        expectOwnActive.add(sessionId);
    }

    const acc: StreamAccumulator = { askQuestions: null };

    const workspaceDir = WORKSPACE_DIR;
    const projectId = await projectIdForPath(workspaceDir);

    const effects: StreamEffects = {
        runId,
        getSessionId: () => getChatState().sessionId,
        setSessionId: (id) => getChatState().setSessionId(id),
        markOwnActive: (id) => expectOwnActive.add(id),
        getApproval: () => useApprovalStore.getState().pending,
        setApproval: (pending) => useApprovalStore.getState().setPending(pending),
        setAskActive: (questions) => useAskUserStore.getState().setActive(questions),
        setCtx: (used, limit, percent) =>
            useCtxStore.getState().setCtx(used, limit, percent),
        setTodos: (input) => useTodoStore.getState().setTodos(parseTodos(input)),
        startCompaction: (messages, tokens) =>
            useCompactionStore.getState().start(messages, tokens),
        endCompaction: () => useCompactionStore.getState().end(),
        setRetry: (retry) => getChatState().setRetry(retry),
        setPending: (messageId, pending) =>
            getChatState().setPending(messageId, pending),
        insertWakeMessage: (text, wakeFor, variant) =>
            getChatState().insertWakeMessage(text, wakeFor, variant),
        startTextPart: (messageId) => getChatState().startTextPart(messageId),
        appendTextDelta: (messageId, delta) =>
            getChatState().appendTextDelta(messageId, delta),
        startReasoningPart: (messageId) =>
            getChatState().startReasoningPart(messageId),
        appendReasoningDelta: (messageId, delta) =>
            getChatState().appendReasoningDelta(messageId, delta),
        endReasoningPart: (messageId, elapsedMs) =>
            getChatState().endReasoningPart(messageId, elapsedMs),
        startToolCall: (messageId, tool) =>
            getChatState().startToolCall(messageId, tool),
        setToolInput: (messageId, toolCallId, input) =>
            getChatState().setToolInput(messageId, toolCallId, input),
        setToolOutput: (messageId, toolCallId, output) =>
            getChatState().setToolOutput(messageId, toolCallId, output),
        setToolStatus: (messageId, toolCallId, status) =>
            getChatState().setToolStatus(messageId, toolCallId, status),
        failToolCall: (messageId, toolCallId, message) =>
            getChatState().failToolCall(messageId, toolCallId, message),
    };

    try {
        await streamChat({
            message: options.message,
            sessionId,
            workspaceDir,
            projectId,
            provider,
            model,
            agentKey,
            reasoningEffort,
            resumeFromSequence: options.resumeFromSequence ?? null,
            onEvent: (event) => {
                applyStreamEvent(event, assistantId, effects, acc);
            },
        });
        getChatState().completeStream();
        clearStaleApproval(runId, false);
    } catch (err) {
        getChatState().failStream(
            err instanceof Error ? err.message : String(err),
        );
        clearStaleApproval(runId, true);
    } finally {
        const finishedSessionId = sessionId ?? getChatState().sessionId;
        if (finishedSessionId) {
            expectOwnActive.delete(finishedSessionId);
            // A wake went active while this stream was still draining; tail it
            // now that the local stream is gone.
            if (pendingTail.delete(finishedSessionId)) {
                void resumeChatStream(finishedSessionId);
            }
        }
        // A stream that dies mid-compaction never delivers compaction-end, so
        // the banner would spin forever without this.
        useCompactionStore.getState().end();
    }
}
