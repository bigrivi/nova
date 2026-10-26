/**
 * Stream event handlers: one function per event family, no transport and no
 * direct store imports. `chat-stream` supplies the side effects, so each handler
 * is testable with a fake context.
 */
import type { NovaStreamEvent } from "../api/types.ts";
import type { ApprovalPending } from "../stores/approval-store.ts";
import type { AskQuestion } from "../stores/ask-user-store.ts";
import type { RetryState, ToolCallPart } from "../stores/chat-store.ts";

/** Mutable per-turn state the handlers accumulate across events. */
export type StreamAccumulator = {
    askQuestions: AskQuestion[] | null;
};

/** Side effects one turn can produce. */
export type StreamEffects = {
    runId: number;
    getSessionId(): string | null;
    setSessionId(sessionId: string): void;
    markOwnActive(sessionId: string): void;
    getApproval(): ApprovalPending | null;
    setApproval(pending: ApprovalPending | null): void;
    setAskActive(questions: AskQuestion[] | null): void;
    setCtx(used: number, limit: number, percent: number): void;
    setTodos(input: unknown): void;
    startCompaction(messageCount: number, tokenCount: number): void;
    endCompaction(): void;
    setRetry(retry: RetryState | null): void;

    setPending(messageId: string, pending: boolean): void;
    insertWakeMessage(text: string, wakeFor: string, variant?: string): void;
    startTextPart(messageId: string): void;
    appendTextDelta(messageId: string, delta: string): void;
    startReasoningPart(messageId: string): void;
    appendReasoningDelta(messageId: string, delta: string): void;
    endReasoningPart(messageId: string, elapsedMs: number | null): void;
    startToolCall(
        messageId: string,
        tool: { toolCallId: string; toolName: string },
    ): void;
    setToolInput(messageId: string, toolCallId: string, input: unknown): void;
    setToolOutput(messageId: string, toolCallId: string, output: unknown): void;
    setToolStatus(
        messageId: string,
        toolCallId: string,
        status: Extract<ToolCallPart["status"], "blocked">,
    ): void;
    failToolCall(messageId: string, toolCallId: string, message: string): void;
};

type EventData = Record<string, unknown>;

function text(data: EventData, key: string): string {
    const value = data[key];
    return typeof value === "string" ? value : "";
}

/** Parse the ask_user tool's input (both {questions:[...]} and {question:{...}}). */
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

/** Read context usage from either the `data` envelope or the event body. */
export function parseContextEvent(event: NovaStreamEvent): {
    used: number;
    limit: number;
    percent: number;
} {
    const source =
        event.data ??
        (event as unknown as {
            used?: number;
            limit?: number;
            percent?: number;
        });
    const used = Number((source as { used?: number }).used ?? 0);
    const limit = Number((source as { limit?: number }).limit ?? 0);
    const percent = Number(
        (source as { percent?: number }).percent ??
            (limit ? Math.round((used / limit) * 100) : 0),
    );
    return { used, limit, percent };
}

function approvalFrom(
    data: EventData,
    sessionId: string,
    runId: number,
): ApprovalPending {
    return {
        sessionId: text(data, "sessionId") || sessionId,
        requestId: text(data, "requestId"),
        command: text(data, "command"),
        description: text(data, "description"),
        toolName: text(data, "toolName"),
        rememberable: data.rememberable !== false,
        family: text(data, "family"),
        target: text(data, "target"),
        scriptScoped: data.scriptScoped === true,
        dangerous: data.dangerous === true,
        workspace: text(data, "workspace"),
        runId,
    };
}

/**
 * Apply one SSE event to the turn's effects.
 *
 * Args:
 *   event: The decoded stream event.
 *   messageId: The assistant message this turn is writing into.
 *   ctx: Side effects supplied by the caller.
 *   acc: Per-turn accumulator (currently the parsed ask_user questions).
 *
 * Raises:
 *   Error: When the event is an `error` frame.
 */
export function applyStreamEvent(
    event: NovaStreamEvent,
    messageId: string,
    ctx: StreamEffects,
    acc: StreamAccumulator,
): void {
    // A retry describes a wait that is happening now, so progress means the
    // wait ended and the line is stale. `finish` is excluded because the turn
    // teardown (completeStream/failStream) clears it.
    if (
        event.type !== "data-nova-retry" &&
        event.type !== "data-nova-heartbeat" &&
        event.type !== "finish"
    ) {
        ctx.setRetry(null);
    }

    switch (event.type) {
        case "data-nova-session": {
            const next = String(event.data?.sessionId ?? "");
            if (next && next !== ctx.getSessionId()) {
                ctx.setSessionId(next);
            }
            if (next) {
                ctx.markOwnActive(next);
            }
            return;
        }
        case "data-nova-wake": {
            // The AI SDK protocol has no user-message frame, so wake text is
            // inserted before the reply it belongs to.
            const data = event.data ?? {};
            const body = text(data, "text");
            const wakeFor = text(data, "messageId");
            const variant = text(data, "variant");
            if (body && wakeFor) {
                ctx.insertWakeMessage(body, wakeFor, variant || undefined);
            }
            return;
        }
        case "start-step": {
            ctx.setPending(messageId, true);
            return;
        }
        case "text-start":
            ctx.startTextPart(messageId);
            return;
        case "text-delta":
            ctx.appendTextDelta(messageId, event.delta ?? "");
            return;
        case "reasoning-start":
            ctx.startReasoningPart(messageId);
            return;
        case "reasoning-delta":
            ctx.appendReasoningDelta(messageId, event.delta ?? "");
            return;
        case "reasoning-end":
            ctx.endReasoningPart(messageId, event.elapsedMs ?? null);
            return;
        case "tool-input-start":
            ctx.startToolCall(messageId, {
                toolCallId: event.toolCallId ?? "",
                toolName: event.toolName ?? "unknown",
            });
            return;
        case "tool-input-available": {
            ctx.setToolInput(messageId, event.toolCallId ?? "", event.input);
            if (event.toolName === "ask_user") {
                acc.askQuestions = parseAskQuestions(event.input);
            }
            if (event.toolName === "todo_write") {
                ctx.setTodos(event.input);
            }
            return;
        }
        case "tool-output-available":
            ctx.setToolOutput(messageId, event.toolCallId ?? "", event.output);
            return;
        case "data-nova-tool-error":
            ctx.failToolCall(
                messageId,
                String(event.data?.toolCallId ?? ""),
                String(event.data?.message ?? "Tool failed"),
            );
            return;
        case "data-nova-approval-required": {
            const data = (event.data ?? {}) as EventData;
            ctx.setApproval(
                approvalFrom(data, ctx.getSessionId() ?? "", ctx.runId),
            );
            const blockedToolCallId = text(data, "toolCallId");
            if (blockedToolCallId) {
                ctx.setToolStatus(messageId, blockedToolCallId, "blocked");
            }
            return;
        }
        case "data-nova-approval-resolved": {
            // A replayed retraction clears a prompt that was already answered,
            // so a resume never resurrects a ghost dialog.
            const requestId = String(event.data?.requestId ?? "");
            const pending = ctx.getApproval();
            if (pending && pending.requestId === requestId) {
                ctx.setApproval(null);
            }
            return;
        }
        case "data-nova-input-required": {
            if (acc.askQuestions && acc.askQuestions.length > 0) {
                ctx.setAskActive(acc.askQuestions);
            }
            return;
        }
        case "abort":
            return;
        case "error":
            throw new Error(event.errorText ?? "Unknown stream error");
        case "data-nova-context": {
            const { used, limit, percent } = parseContextEvent(event);
            ctx.setCtx(used, limit, percent);
            return;
        }
        case "data-nova-compaction-start": {
            const data = (event.data ?? {}) as EventData;
            ctx.startCompaction(
                Number(data.message_count ?? 0),
                Number(data.token_count ?? 0),
            );
            return;
        }
        case "data-nova-compaction-end":
            ctx.endCompaction();
            return;
        case "data-nova-retry": {
            const data = (event.data ?? {}) as EventData;
            ctx.setRetry({
                attempt: Number(data.attempt ?? 0),
                total: Number(data.total ?? 0),
                waitSeconds: Number(data.wait_seconds ?? 0),
                reason: text(data, "reason"),
            });
            return;
        }
        default:
            // data-nova-heartbeat / start / finish
            return;
    }
}
