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
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore, type AskQuestion } from "../stores/ask-user-store.ts";
import { getChatState } from "../stores/chat-store.ts";
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

/** Parse the ask_user tool's input into a list of questions (compatible with both {questions:[...]} and {question:{...}}) */
export function parseAskQuestions(input: unknown): AskQuestion[] {
    if (!input || typeof input !== "object") return [];
    const obj = input as Record<string, unknown>;
    const raw = Array.isArray(obj.questions) ? obj.questions : obj.question;
    const list = Array.isArray(raw) ? raw : raw != null ? [raw] : [];
    const result: AskQuestion[] = [];
    for (let i = 0; i < list.length; i++) {
        const q = list[i];
        if (!q || typeof q !== "object") continue;
        const qo = q as Record<string, unknown>;
        const inputType = String(qo.input_type ?? "text").toLowerCase();
        const options = Array.isArray(qo.options)
            ? qo.options
                  .filter(
                      (o): o is Record<string, unknown> =>
                          !!o && typeof o === "object",
                  )
                  .map((o) => ({
                      label: String(o.label ?? o.value ?? "").trim(),
                      value:
                          o.value !== undefined ? String(o.value) : undefined,
                      description: String(o.description ?? "").trim(),
                  }))
                  .filter((o) => o.label)
            : [];
        result.push({
            id: String(qo.id ?? `q${i}`).trim() || `q${i}`,
            header: String(qo.header ?? "").trim(),
            question: String(qo.question ?? "").trim(),
            inputType:
                inputType === "select"
                    ? "select"
                    : inputType === "textarea"
                      ? "textarea"
                      : "text",
            options,
            multiple: Boolean(qo.multiple),
            required: qo.required !== false,
            default: String(qo.default ?? ""),
        });
    }
    return result;
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
    await runTurn({ message: options.message });
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
    /** Set when tailing an existing turn instead of starting a new one. */
    resumeSessionId?: string;
    /** Sequence cursor; null/undefined starts a fresh turn. */
    resumeFromSequence?: number | null;
};

/** Run one conversation round: optimistically insert the message → consume the stream → finalize the state machine. */
async function runTurn(options: TurnOptions): Promise<void> {
    const store = getChatState();
    const sessionId = options.resumeSessionId ?? store.sessionId;
    const { provider, model } = store;
    const runId = ++runCounter;
    const resuming = options.resumeFromSequence != null;

    if (!resuming) {
        store.addUserMessage(options.message);
    }
    const assistantId = store.startAssistantMessage();
    if (sessionId) {
        expectOwnActive.add(sessionId);
    }

    let pendingAskQuestions: AskQuestion[] | null = null;

    const workspaceDir = WORKSPACE_DIR;
    const projectId = await projectIdForPath(workspaceDir);

    try {
        await streamChat({
            message: options.message,
            sessionId,
            workspaceDir,
            projectId,
            provider,
            model,
            resumeFromSequence: options.resumeFromSequence ?? null,
            onEvent: (event) => {
                const current = getChatState();
                switch (event.type) {
                    case "data-nova-session": {
                        const next = String(event.data?.sessionId ?? "");
                        if (next && next !== current.sessionId) {
                            current.setSessionId(next);
                        }
                        if (next) {
                            expectOwnActive.add(next);
                        }
                        return;
                    }
                    case "data-nova-wake": {
                        // Server-injected user message for a background-task
                        // completion: the AI SDK protocol carries no user
                        // message frame, so insert it before the reply.
                        const data = event.data ?? {};
                        const text =
                            typeof data.text === "string" ? data.text : "";
                        const wakeFor =
                            typeof data.messageId === "string"
                                ? data.messageId
                                : "";
                        if (text && wakeFor) {
                            current.insertWakeMessage(text, wakeFor);
                        }
                        return;
                    }
                    case "start-step": {
                        // Fired on every LLM turn, including the tool-loop calls
                        // after the first. Mark the message pending so the UI can
                        // show the thinking indicator again before the next part.
                        current.setPending(assistantId, true);
                        return;
                    }
                    case "text-start": {
                        current.startTextPart(assistantId);
                        return;
                    }
                    case "text-delta": {
                        current.appendTextDelta(assistantId, event.delta ?? "");
                        return;
                    }
                    case "reasoning-start": {
                        current.startReasoningPart(assistantId);
                        return;
                    }
                    case "reasoning-delta": {
                        current.appendReasoningDelta(
                            assistantId,
                            event.delta ?? "",
                        );
                        return;
                    }
                    case "reasoning-end": {
                        current.endReasoningPart(
                            assistantId,
                            event.elapsedMs ?? null,
                        );
                        return;
                    }
                    case "tool-input-start": {
                        current.startToolCall(assistantId, {
                            toolCallId: event.toolCallId ?? "",
                            toolName: event.toolName ?? "unknown",
                        });
                        return;
                    }
                    case "tool-input-available": {
                        current.setToolInput(
                            assistantId,
                            event.toolCallId ?? "",
                            event.input,
                        );
                        if (event.toolName === "ask_user") {
                            pendingAskQuestions = parseAskQuestions(
                                event.input,
                            );
                        }
                        if (event.toolName === "todo_write") {
                            useTodoStore
                                .getState()
                                .setTodos(parseTodos(event.input));
                        }
                        return;
                    }
                    case "tool-output-available": {
                        current.setToolOutput(
                            assistantId,
                            event.toolCallId ?? "",
                            event.output,
                        );
                        return;
                    }
                    case "data-nova-tool-error": {
                        current.failToolCall(
                            assistantId,
                            String(event.data?.toolCallId ?? ""),
                            String(event.data?.message ?? "Tool failed"),
                        );
                        return;
                    }
                    case "data-nova-approval-required": {
                        useApprovalStore.getState().setPending({
                            sessionId: String(
                                event.data?.sessionId ||
                                    current.sessionId ||
                                    "",
                            ),
                            requestId: String(event.data?.requestId ?? ""),
                            command: String(event.data?.command ?? ""),
                            description: String(event.data?.description ?? ""),
                            runId,
                        });
                        const blockedToolCallId = String(
                            event.data?.toolCallId ?? "",
                        );
                        if (blockedToolCallId) {
                            current.setToolStatus(
                                assistantId,
                                blockedToolCallId,
                                "blocked",
                            );
                        }
                        return;
                    }
                    case "data-nova-input-required": {
                        if (
                            pendingAskQuestions &&
                            pendingAskQuestions.length > 0
                        ) {
                            useAskUserStore
                                .getState()
                                .setActive(pendingAskQuestions);
                        }
                        // The server will follow with finish + [DONE], so the stream ends naturally;
                        // do not call completeStream here to avoid synchronously triggering a React update in the SSE callback
                        return;
                    }
                    case "abort": {
                        // Same as above: wait for the stream to end naturally; finalize uniformly after resolve
                        return;
                    }
                    case "error": {
                        throw new Error(
                            event.errorText ?? "Unknown stream error",
                        );
                    }
                    case "data-nova-context": {
                        const ctxData = (event as unknown as { data?: { used?: number; limit?: number; percent?: number } }).data;
                        const d = ctxData ?? (event as unknown as { used?: number; limit?: number; percent?: number });
                        const used = Number((d as { used?: number }).used ?? 0);
                        const limit = Number((d as { limit?: number }).limit ?? 0);
                        const percent = Number(
                            (d as { percent?: number }).percent ?? (limit ? Math.round((used / limit) * 100) : 0),
                        );
                        useCtxStore.getState().setCtx(used, limit, percent);
                        return;
                    }
                    case "data-nova-compaction-start": {
                        const d = (event as unknown as {
                            data?: { message_count?: number; token_count?: number };
                        }).data;
                        useCompactionStore
                            .getState()
                            .start(
                                Number(d?.message_count ?? 0),
                                Number(d?.token_count ?? 0),
                            );
                        return;
                    }
                    case "data-nova-compaction-end": {
                        useCompactionStore.getState().end();
                        return;
                    }
                    default:
                        // data-nova-heartbeat / start / finish
                        return;
                }
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
