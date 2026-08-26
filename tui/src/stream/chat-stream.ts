/** Chat stream processing state machine: SSE events → store updates (pure logic, no UI dependencies)
 *
 * Event protocol per nova/server/ai_sdk_stream.py + frontend/src/app/NovaAppShell.tsx:
 * - data-nova-session       first-session creation, records the sessionId, reused by later messages
 * - text-* / reasoning-*    text and reasoning streams
 * - tool-input-* / tool-output-available / data-nova-tool-error   tool calls
 * - data-nova-approval-required  command approval pending → approval store
 * - data-nova-input-required     ask_user pending → activate the ask-user form
 * - abort / finish / error  finalization
 */
import { streamChat } from "../api/nova-api.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore, type AskQuestion } from "../stores/ask-user-store.ts";
import { getChatState } from "../stores/chat-store.ts";
import {
    parseTodos,
    useTodoStore,
} from "../stores/todo-store.ts";

export type ChatRunOptions = {
    message: string;
};

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
        result.push({
            id: String(qo.id ?? `q${i}`),
            header: String(qo.header ?? ""),
            question: String(qo.question ?? ""),
            inputType:
                inputType === "select"
                    ? "select"
                    : inputType === "confirm"
                      ? "confirm"
                      : "text",
            options: Array.isArray(qo.options)
                ? qo.options
                      .filter(
                          (o): o is Record<string, unknown> =>
                              !!o && typeof o === "object",
                      )
                      .map((o) => ({
                          label: String(o.label ?? o.value ?? ""),
                          value:
                              o.value !== undefined
                                  ? String(o.value)
                                  : undefined,
                      }))
                : [],
            multiple: Boolean(qo.multiple),
            required: qo.required !== false,
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

/** Run one conversation round: optimistically insert the message → consume the stream → finalize the state machine. */
export async function runChatStream(options: ChatRunOptions): Promise<void> {
    const store = getChatState();
    const { sessionId, provider, model } = store;

    store.addUserMessage(options.message);
    const assistantId = store.startAssistantMessage();

    let pendingAskQuestions: AskQuestion[] | null = null;

    try {
        await streamChat({
            message: options.message,
            sessionId,
            provider,
            model,
            onEvent: (event) => {
                const current = getChatState();
                switch (event.type) {
                    case "data-nova-session": {
                        const next = String(event.data?.sessionId ?? "");
                        if (next && next !== current.sessionId) {
                            current.setSessionId(next);
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
                                event.data?.sessionId ??
                                    current.sessionId ??
                                    "",
                            ),
                            requestId: String(event.data?.requestId ?? ""),
                            command: String(event.data?.command ?? ""),
                            description: String(event.data?.description ?? ""),
                        });
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
                    default:
                        // data-nova-heartbeat / data-nova-compaction-* / start / finish
                        return;
                }
            },
        });
        getChatState().completeStream();
    } catch (err) {
        getChatState().failStream(
            err instanceof Error ? err.message : String(err),
        );
    }
}
