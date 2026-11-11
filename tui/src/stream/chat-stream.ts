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
 *
 * Every turn is bound to one session tab. Inactive tabs keep their own stream,
 * so switching tabs never interrupts or replays a turn this client started.
 */
import {
    interruptChat,
    resolveProject,
    regenerateChat,
    streamChat,
    type StreamChatOptions,
} from "../api/nova-api.ts";
import { regenerateTarget } from "../lib/regenerate-target.ts";
import {
    applyStreamEvent,
    type StreamAccumulator,
    type StreamEffects,
} from "./apply-event.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore, type AskQuestion } from "../stores/ask-user-store.ts";
import {
    chatSlice,
    getChatState,
    useChatStore,
} from "../stores/chat-store.ts";
import { useCompactionStore } from "../stores/compaction-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { usePermissionStore } from "../stores/permission-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { parseTodos, useTodoStore } from "../stores/todo-store.ts";
import { activeTab, tabForSession, setTabSequence, tabSequence, useTabStore, NEW_TAB_TITLE } from "../stores/tab-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";
import { truncateEnd } from "../lib/display-width.ts";
import type { NovaAttachmentData, NovaStreamEvent } from "../api/types.ts";

export type ChatRunOptions = {
    message: string;
    /** What the transcript shows; defaults to `message`. */
    displayText?: string;
    /** Images pasted into the composer; the backend folds them into the turn. */
    attachments?: NovaAttachmentData[];
    /** Target tab; defaults to the active tab. */
    tabId?: string;
};

/** The TUI keeps one working directory for its lifetime, so resolve it once. */
let resolvedProject: { path: string; id: string } | null = null;

async function projectIdForPath(path: string): Promise<string | null> {
    if (resolvedProject?.path === path) {
        return resolvedProject.id;
    }
    let project;
    try {
        project = await resolveProject(path);
    } catch {
        // A project lookup is a nicety; failing it must not take the turn with
        // it. The session still runs, just without a project label.
        return null;
    }
    if (!project) {
        return null;
    }
    resolvedProject = { path, id: project.id };
    return project.id;
}

/** Monotonic id per runTurn call: lets stream teardown clear only the
 * approval its own run created, never a newer live one from a later run. */
let runCounter = 0;

/** Session ids whose next `state: active` event is this client's own turn. */
const expectOwnActive = new Set<string>();
/** Active events that arrived while a local stream was still draining. */
const pendingTail = new Set<string>();
/** Live readers keyed by tab id, so closing a tab can drop only its own. */
const controllers = new Map<string, AbortController>();

/** Consume the "this active event is our own turn" marker. */
export function consumeOwnActive(sessionId: string): boolean {
    return expectOwnActive.delete(sessionId);
}

/** Park a wake request for the draining stream's cleanup to tail. */
export function parkTail(sessionId: string): void {
    pendingTail.add(sessionId);
}

/** Drop the local reader for one tab; the server turn keeps running detached. */
export function abortTabStream(tabId: string): void {
    controllers.get(tabId)?.abort();
    controllers.delete(tabId);
}

/** Ensure the app has a tab to stream into (launch screen has none yet). */
function ensureActiveTab(): string {
    const store = useTabStore.getState();
    if (store.activeId) {
        return store.activeId;
    }
    const tab = store.create();
    useChatStore.getState().activate(tab.id, null);
    store.select(tab.id);
    return tab.id;
}

/** Drop a pending approval created by *this* run when its stream ends with
 * the dialog still showing: the backend unregisters in its finally, so the
 * dialog is unresolvable (any later y → 404). Notify on abnormal end only. */
function clearStaleApproval(runId: number, notify: boolean): void {
    const store = useApprovalStore.getState();
    const owned =
        store.pending?.runId === runId ||
        store.queue.some((item) => item.runId === runId);
    if (!owned) {
        return;
    }
    store.clearRun(runId);
    if (notify) {
        useToastStore
            .getState()
            .show(
                "Approval expired: the request ended before it was answered.",
                4000,
            );
    }
}

/** Keep the tab badge only if the promoted question belongs to the same tab. */
function clearAskAttention(tabId: string | null | undefined): void {
    if (!tabId) return;
    const state = useAskUserStore.getState();
    useTabStore
        .getState()
        .setAttention(
            tabId,
            state.activeTabId === tabId ? "question" : null,
        );
}

/** Submit ask_user answers: clears the active form and starts a new stream */
export async function submitAskAnswers(
    questions: AskQuestion[],
    answers: Record<string, string>,
): Promise<void> {
    // Capture the owning tab before clearing: promoting the next queued
    // question may switch tabs, and the answers must go to the tab that asked.
    const tabId = activeTab()?.id;
    useAskUserStore.getState().setActive(null);
    clearAskAttention(tabId);
    const text = formatAskAnswers(questions, answers);
    if (text) {
        await runChatStream({ message: text, tabId });
    }
}

/** Cancel the active ask_user form and report cancellation to the model */
export async function submitAskCancel(
    questions: AskQuestion[],
): Promise<void> {
    const tabId = activeTab()?.id;
    useAskUserStore.getState().setActive(null);
    clearAskAttention(tabId);
    const skipped = questions
        .map((q) => `Q (${q.id}): [cancelled by user]`)
        .join("\n");
    await runChatStream({ message: skipped || "[cancelled by user]", tabId });
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

/** Last requestInterrupt post: one ESC keypress reaches both the composer and
the global handler, and key repeat fires fast, so guard here for one post. */
let lastInterruptAt = 0;

type InterruptTransport = (sessionId: string) => Promise<boolean | null>;

let interruptTransport: InterruptTransport = interruptChat;

/** Replace the interrupt request in tests; null restores the real client. */
export function setInterruptTransportForTest(
    transport: InterruptTransport | null,
): void {
    interruptTransport = transport ?? interruptChat;
}

/** Reset the interrupt guard (tests only). */
export function resetInterruptGuardForTest(): void {
    lastInterruptAt = 0;
}

type StreamTransport = (options: StreamChatOptions) => Promise<void>;

let streamTransport: StreamTransport = streamChat;

/** Replace the stream request in tests; null restores the real client. */
export function setStreamTransportForTest(
    transport: StreamTransport | null,
): void {
    streamTransport = transport ?? streamChat;
}

/** Cancel the live turn from any ESC entry point: no-op off-stream, one post per keypress. */
export async function requestInterrupt(): Promise<void> {
    const tab = activeTab();
    const sessionId = tab?.sessionId ?? getChatState().sessionId;
    const isStreaming = tab
        ? chatSlice(tab.id).isStreaming
        : getChatState().isStreaming;
    if (!isStreaming || !sessionId) {
        return;
    }
    const now = Date.now();
    if (now - lastInterruptAt < 500) {
        return;
    }
    lastInterruptAt = now;
    const outcome = await interruptTransport(sessionId);
    if (outcome === false) {
        useToastStore.getState().show("Nothing to cancel: this turn already ended.");
    } else if (outcome === null) {
        useToastStore.getState().show("Could not reach the server to cancel.");
    }
}

/**
 * Re-run the last answer of the active tab.
 *
 * The user message stays; the answer that followed it is replaced. The server
 * drops the old answer itself, so the local bubble is reset rather than left
 * holding two answers.
 */
export async function regenerateLastAnswer(): Promise<void> {
    const tabId = ensureActiveTab();
    const slice = chatSlice(tabId);
    if (!slice.sessionId) {
        useToastStore.getState().show("Nothing to regenerate: no session yet.");
        return;
    }
    const target = regenerateTarget(slice.messages);
    if (target.kind === "none") {
        useToastStore.getState().show(target.reason);
        return;
    }
    await runTurn({
        tabId,
        message: "",
        regenerate: true,
        regenerateAssistantId:
            target.kind === "replace" ? target.messageId : undefined,
    });
}

/** Run one user-initiated conversation round in the active tab. */
export async function runChatStream(options: ChatRunOptions): Promise<void> {
    await runTurn({
        ...options,
        tabId: options.tabId ?? ensureActiveTab(),
    });
}

/**
 * Tail a server-initiated or already-running turn without sending a message.
 *
 * A background task completion wakes its session with a headless turn after the
 * original SSE closed. Reattaching with a sequence cursor replays that turn and
 * follows it live, so the wake message and reply appear in place.
 */
export async function resumeChatStream(sessionId: string): Promise<void> {
    const tab = tabForSession(sessionId);
    if (!tab) {
        return;
    }
    if (chatSlice(tab.id).isStreaming) {
        parkTail(sessionId);
        return;
    }
    await runTurn({
        tabId: tab.id,
        message: "",
        resumeSessionId: sessionId,
        resumeFromSequence: tabSequence(tab.id),
    });
}

type TurnOptions = {
    tabId: string;
    message: string;
    displayText?: string;
    /** Set when tailing an existing turn instead of starting a new one. */
    resumeSessionId?: string;
    /** Sequence cursor; null/undefined starts a fresh turn. */
    resumeFromSequence?: number | null;
    attachments?: NovaAttachmentData[];
    /** Re-run the last answer instead of sending a new message. */
    regenerate?: boolean;
    /** The assistant bubble the new answer replaces; absent means "append one". */
    regenerateAssistantId?: string;
};

/** Run one conversation round: optimistically insert the message → consume the stream → finalize the state machine. */
async function runTurn(options: TurnOptions): Promise<void> {
    const tab = useTabStore
        .getState()
        .tabs.find((item) => item.id === options.tabId);
    if (!tab) {
        return;
    }
    const tabId = tab.id;
    const slice = chatSlice(tabId);
    const sessionId = options.resumeSessionId ?? slice.sessionId ?? tab.sessionId;
    let liveSessionId = sessionId;
    const runId = ++runCounter;
    const resuming = options.resumeFromSequence != null;

    const regenerating = options.regenerate === true;
    if (!resuming && !regenerating) {
        const display = options.displayText ?? options.message;
        useChatStore
            .getState()
            .addUserMessage(
                // The `Attached file:` lines are for the model; the bubble shows
                // what the user actually typed.
                display,
                options.attachments?.map((attachment) => attachment.name),
                tabId,
            );
        // Optimistic title until the server publishes its own, matching the
        // web frontend: an untitled tab is hard to pick out of a strip.
        if (tab.title === NEW_TAB_TITLE) {
            const title = display.replace(/\s+/g, " ").trim();
            if (title) {
                useTabStore.getState().renameTab(tabId, truncateEnd(title, 40));
            }
        }
    }
    // A regeneration replaces the answer already on screen, so it streams into
    // the same bubble instead of adding a second one.
    const assistantId =
        regenerating && options.regenerateAssistantId
            ? options.regenerateAssistantId
            : useChatStore.getState().startAssistantMessage(tabId);
    if (regenerating && options.regenerateAssistantId) {
        useChatStore.getState().resetAssistantMessage(assistantId, tabId);
    }
    if (sessionId) {
        expectOwnActive.add(sessionId);
    }

    const acc: StreamAccumulator = { askQuestions: null };
    const projectId = await projectIdForPath(WORKSPACE_DIR);
    if (!useTabStore.getState().tabs.some((item) => item.id === tabId)) {
        return;
    }
    const controller = new AbortController();
    controllers.set(tabId, controller);
    const isActive = () => useTabStore.getState().activeId === tabId;
    let sawFrame = false;

    const effects: StreamEffects = {
        runId,
        getSessionId: () => chatSlice(tabId).sessionId,
        setSessionId: (id) => {
            liveSessionId = id;
            useChatStore.getState().setSessionId(id, tabId);
            useTabStore.getState().adopt(tabId, id);
        },
        markOwnActive: (id) => expectOwnActive.add(id),
        getApproval: () => useApprovalStore.getState().pending,
        setApproval: (pending) => {
            useApprovalStore.getState().setPending(pending);
            if (pending) {
                useTabStore.getState().setAttention(tabId, "approval");
            }
        },
        resolveApproval: (requestId) => {
            useApprovalStore.getState().resolve(requestId);
            const head = useApprovalStore.getState().pending;
            useTabStore
                .getState()
                .setAttention(
                    tabId,
                    head && head.sessionId === chatSlice(tabId).sessionId
                        ? "approval"
                        : null,
                );
        },
        setAskActive: (questions) => {
            useAskUserStore.getState().setActive(questions, tabId);
            const state = useAskUserStore.getState();
            useTabStore
                .getState()
                .setAttention(
                    tabId,
                    state.active !== null && state.activeTabId === tabId
                        ? "question"
                        : null,
                );
        },
        setCtx: (used, limit, percent) => {
            if (isActive()) {
                useCtxStore.getState().setCtx(used, limit, percent);
            }
        },
        setTodos: (input) => {
            if (isActive()) {
                useTodoStore.getState().setTodos(parseTodos(input));
            }
        },
        startCompaction: (messages, tokens) => {
            if (isActive()) {
                useCompactionStore.getState().start(messages, tokens);
            }
        },
        endCompaction: () => {
            if (isActive()) {
                useCompactionStore.getState().end();
            }
        },
        setRetry: (retry) => useChatStore.getState().setRetry(retry, tabId),
        setPending: (messageId, pending) =>
            useChatStore.getState().setPending(messageId, pending, tabId),
        insertWakeMessage: (text, wakeFor, variant) =>
            useChatStore
                .getState()
                .insertWakeMessage(text, wakeFor, variant, tabId),
        startTextPart: (messageId) =>
            useChatStore.getState().startTextPart(messageId, tabId),
        appendTextDelta: (messageId, delta) =>
            useChatStore.getState().appendTextDelta(messageId, delta, tabId),
        startReasoningPart: (messageId) =>
            useChatStore.getState().startReasoningPart(messageId, tabId),
        appendReasoningDelta: (messageId, delta) =>
            useChatStore
                .getState()
                .appendReasoningDelta(messageId, delta, tabId),
        endReasoningPart: (messageId, elapsedMs) =>
            useChatStore
                .getState()
                .endReasoningPart(messageId, elapsedMs, tabId),
        startToolCall: (messageId, tool) =>
            useChatStore.getState().startToolCall(messageId, tool, tabId),
        setToolInput: (messageId, toolCallId, input) =>
            useChatStore
                .getState()
                .setToolInput(messageId, toolCallId, input, tabId),
        setToolOutput: (messageId, toolCallId, output) =>
            useChatStore
                .getState()
                .setToolOutput(messageId, toolCallId, output, tabId),
        setToolStatus: (messageId, toolCallId, status) =>
            useChatStore
                .getState()
                .setToolStatus(messageId, toolCallId, status, tabId),
        failToolCall: (messageId, toolCallId, message) =>
            useChatStore
                .getState()
                .failToolCall(messageId, toolCallId, message, tabId),
    };

    const onEvent = (event: NovaStreamEvent): void => {
        sawFrame = true;
        applyStreamEvent(event, assistantId, effects, acc);
    };
    const onSequence = (sequence: number): void =>
        setTabSequence(tabId, sequence);
    const onResync = (): void =>
        useChatStore.getState().resetAssistantMessage(assistantId, tabId);

    try {
        if (regenerating) {
            if (!sessionId) {
                useChatStore.getState().failStream("No session to regenerate.", tabId);
                return;
            }
            await regenerateChat({
                sessionId,
                provider: slice.provider,
                model: slice.model,
                reasoningEffort: slice.reasoningEffort,
                permissionMode: usePermissionStore.getState().mode,
                signal: controller.signal,
                onSequence,
                onResync,
                onEvent,
            });
        } else {
            await streamTransport({
                message: options.message,
                displayText: options.displayText,
                sessionId,
                // The attachments carry the images themselves. Dropping them here
                // leaves the model with a chip in the transcript and no picture.
                attachments: options.attachments,
                workspaceDir: WORKSPACE_DIR,
                projectId,
                provider: slice.provider,
                model: slice.model,
                agentKey: slice.agentKey,
                reasoningEffort: slice.reasoningEffort,
                permissionMode: usePermissionStore.getState().mode,
                resumeFromSequence: options.resumeFromSequence ?? null,
                signal: controller.signal,
                onSequence,
                onResync,
                onEvent,
            });
        }
        if (resuming && !sawFrame) {
            // The server had already finished the turn: reattaching produced no
            // frames, so do not leave an empty assistant bubble behind.
            useChatStore.getState().dropMessage(assistantId, tabId);
            useChatStore.getState().completeStream(tabId);
            return;
        }
        useChatStore.getState().completeStream(tabId);
        useTabStore.getState().markTurnEnded(tabId, true);
        clearStaleApproval(runId, false);
    } catch (err) {
        // A closed tab drops its reader; the server turn keeps running and is
        // picked up again by a cursor resume when the session is reopened.
        if (controller.signal.aborted) {
            return;
        }
        useChatStore
            .getState()
            .failStream(
                err instanceof Error ? err.message : String(err),
                tabId,
            );
        useTabStore.getState().markTurnEnded(tabId, false);
        clearStaleApproval(runId, true);
    } finally {
        controllers.delete(tabId);
        const finishedSessionId =
            liveSessionId ?? chatSlice(tabId).sessionId;
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
        if (isActive()) {
            useCompactionStore.getState().end();
        }
        // A prompt this turn was waiting on is no longer answerable once the
        // stream is gone. Keep the badge only while a request is still queued.
        const approval = useApprovalStore.getState().pending;
        const ask = useAskUserStore.getState();
        useTabStore.getState().setAttention(
            tabId,
            ask.activeTabId === tabId
                ? "question"
                : approval?.runId === runId
                  ? "approval"
                  : null,
        );
        // The tab may have been closed while this turn was still running. Its
        // reader was deliberately kept alive to let the server finish; once it
        // has, the hidden slice is no longer needed.
        if (!useTabStore.getState().tabs.some((item) => item.id === tabId)) {
            useChatStore.getState().remove(tabId);
        }
    }
}
