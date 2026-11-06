/**
 * Binds one tab to one chat stream.
 *
 * Closing a tab closes only the local reader; the server parks the turn as
 * detached and keeps running. Resuming replays from the tab's cursor.
 */
import { openChatStream, type ChatStreamHandle } from "../api/chat-stream";
import { getStreamStatus, approveCommand, interruptChat } from "../api/client";
import type {
    ApprovalRequest,
    NovaAttachmentData,
    NovaStreamEvent,
} from "../api/types";
import {
    cancelAskText,
    formatAskAnswers,
    parseAskQuestions,
    type AskQuestion,
} from "../chat/ask";
import { parseTodos } from "../chat/todo";
import {
    useAttachments,
    type PendingAttachment,
} from "../state/attachments";
import { useChat, chatSlice } from "../state/chat";
import { useRoute } from "../state/route";
import { useSessions } from "../state/sessions";
import { useTabs } from "../state/tabs";
import { TabSequences } from "../tabs/sequences";
import { firstLine } from "./text";

const sequences = new TabSequences();
const streams = new Map<string, ChatStreamHandle>();

function openTabIds(): Set<string> {
    return new Set(useTabs.getState().tabs.map((tab) => tab.id));
}

export function tabSequence(tabId: string): number {
    return sequences.get(tabId);
}

export function setTabSequence(tabId: string, sequence: number): void {
    sequences.set(tabId, sequence, openTabIds());
}

function parseApproval(event: NovaStreamEvent): ApprovalRequest {
    const data = event.data ?? {};
    return {
        requestId: String(data.requestId ?? ""),
        command: String(data.command ?? ""),
        description: String(data.description ?? ""),
        toolName: String(data.toolName ?? "shell"),
        rememberable: data.rememberable !== false,
        family: String(data.family ?? ""),
        target: String(data.target ?? ""),
        scriptScoped: data.scriptScoped === true,
        dangerous: data.dangerous === true,
        workspace: String(data.workspace ?? ""),
    };
}

function jsonText(value: unknown): string {
    if (typeof value === "string") {
        return value;
    }
    if (value === undefined || value === null) {
        return "";
    }
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

function applyEvent(tabId: string, event: NovaStreamEvent): void {
    const chat = useChat.getState();

    // A retry line is only true until the request moves on. Heartbeats are the
    // one frame that does not mean progress; every other non-retry frame clears
    // it, the same rule the web stream uses.
    if (
        event.type !== "data-nova-retry" &&
        event.type !== "data-nova-heartbeat"
    ) {
        chat.setRetry(tabId, null);
    }

    switch (event.type) {
        case "data-nova-retry": {
            const data = event.data ?? {};
            chat.setRetry(tabId, {
                attempt: Number(data.attempt ?? 0),
                total: Number(data.total ?? 0),
                waitSeconds: Number(data.wait_seconds ?? 0),
                reason: String(data.reason ?? ""),
            });
            return;
        }
        case "data-nova-heartbeat":
            return;
        case "text-delta":
            chat.appendText(tabId, event.delta ?? "");
            return;
        case "reasoning-start":
            chat.appendReasoning(tabId, "");
            return;
        case "reasoning-delta":
            chat.appendReasoning(tabId, event.delta ?? "");
            return;
        case "reasoning-end":
            chat.endReasoning(tabId, Number(event.elapsedMs ?? 0));
            return;
        case "tool-input-start":
            if (event.toolCallId) {
                chat.upsertTool(tabId, {
                    toolCallId: event.toolCallId,
                    toolName: event.toolName,
                    status: "running",
                });
            }
            return;
        case "tool-input-available":
            if (event.toolName === "ask_user") {
                const questions = parseAskQuestions(event.input);
                if (questions.length > 0) {
                    chat.setAsk(tabId, questions);
                }
            }
            if (event.toolName === "todo_write") {
                chat.setTodos(tabId, parseTodos(event.input));
            }
            if (event.toolCallId) {
                chat.upsertTool(tabId, {
                    toolCallId: event.toolCallId,
                    toolName: event.toolName,
                    inputText: jsonText(event.input),
                    status: "running",
                });
            }
            return;
        case "tool-output-available":
            if (event.toolCallId) {
                chat.upsertTool(tabId, {
                    toolCallId: event.toolCallId,
                    outputText: jsonText(event.output),
                    status: "done",
                });
            }
            return;
        case "data-nova-tool-error":
            if (event.toolCallId) {
                chat.upsertTool(tabId, {
                    toolCallId: event.toolCallId,
                    status: "error",
                    error: String(event.data?.message ?? "Tool failed"),
                });
            }
            return;
        case "data-nova-approval-required": {
            const approval = parseApproval(event);
            chat.setApproval(tabId, approval);
            useTabs.getState().setAttention(tabId, "approval");
            return;
        }
        case "data-nova-approval-resolved":
            chat.setApproval(tabId, null);
            useTabs.getState().setAttention(tabId, null);
            return;
        case "data-nova-context": {
            const data = event.data ?? {};
            const used = Number(data.used ?? 0);
            const limit = Number(data.limit ?? 0);
            const percent = Number(data.percent ?? 0);
            if (Number.isFinite(used) && Number.isFinite(limit) && limit > 0) {
                chat.setContext(tabId, { used, limit, percent });
            }
            return;
        }
        case "data-nova-compaction-start":
            chat.setCompacting(tabId, true);
            return;
        case "data-nova-compaction-delta":
            chat.appendCompaction(
                tabId,
                String(event.data?.delta ?? ""),
            );
            return;
        case "data-nova-compaction-end":
            chat.setCompacting(tabId, false);
            return;
        case "data-nova-input-required":
            chat.setRequiresInput(
                tabId,
                String(event.data?.message ?? "The agent is waiting for input"),
            );
            useTabs.getState().setAttention(tabId, "question");
            return;
        case "data-nova-wake": {
            const text = String(event.data?.message ?? "");
            if (text) {
                chat.appendUserMessage(
                    tabId,
                    text,
                    String(event.data?.variant ?? "subagent"),
                );
            }
            return;
        }
        default:
            return;
    }
}

function startStream(options: {
    tabId: string;
    sessionId: string | null;
    message: string;
    provider?: string;
    model?: string;
    agentKey?: string;
    projectId?: string | null;
    reasoningEffort?: string | null;
    attachments?: NovaAttachmentData[];
    regenerate?: boolean;
    resumeFromSequence?: number | null;
    resuming?: boolean;
}): void {
    const { tabId } = options;
    let sawFrame = false;

    const handle = openChatStream({
        sessionId: options.sessionId,
        message: options.message,
        provider: options.provider,
        model: options.model,
        agentKey: options.agentKey,
        projectId: options.projectId,
        reasoningEffort: options.reasoningEffort,
        attachments: options.attachments,
        regenerate: options.regenerate,
        resumeFromSequence: options.resumeFromSequence ?? null,
        onSequence: (sequence) => setTabSequence(tabId, sequence),
        onSession: (sessionId) => {
            useChat.getState().setSessionId(tabId, sessionId);
            useTabs.getState().adopt(tabId, sessionId);
        },
        onEvent: (event) => {
            if (options.regenerate && !sawFrame) {
                // The server has already dropped the old answer by the time the
                // first frame arrives, so this is the earliest safe moment to
                // mirror it locally.
                useChat.getState().dropLastAssistant(tabId);
                useChat.getState().startAssistant(tabId);
            }
            sawFrame = true;
            applyEvent(tabId, event);
        },
        onDone: (reason, message) => {
            streams.delete(tabId);
            if (reason === "error" && options.regenerate && !sawFrame) {
                // Nothing was dropped locally and nothing streamed: keep the
                // transcript as it was and surface the failure as a banner.
                useChat.getState().setStreaming(tabId, false);
                useChat
                    .getState()
                    .setError(tabId, message || "The turn failed");
                useTabs.getState().markTurnEnded(tabId, false);
                useTabs.getState().setAttention(tabId, null);
                return;
            }
            if (reason === "error") {
                useChat.getState().finishTurn(tabId, message || "The turn failed");
                useTabs.getState().markTurnEnded(tabId, false);
            } else {
                useChat.getState().finishTurn(tabId);
                useTabs.getState().markTurnEnded(tabId, true);
            }
            useTabs.getState().setAttention(tabId, null);
            if (options.resuming && !sawFrame) {
                useChat.getState().dropEmptyAssistant(tabId);
            }
        },
    });

    streams.set(tabId, handle);
}

/** Send a new user message and start its turn. */
export function runTurn(
    tabId: string,
    text: string,
    attachments: readonly PendingAttachment[] = [],
): void {
    const slice = chatSlice(tabId);
    if (slice.streaming) {
        return;
    }
    const tab = useTabs.getState().tabs.find((item) => item.id === tabId);
    if (tab && tab.title === "New session") {
        useTabs
            .getState()
            .rename(tabId, text.trim() ? firstLine(text, 32) : "Attachment");
    }

    const payload: NovaAttachmentData[] = attachments.map((attachment) =>
        attachment.kind === "image"
            ? {
                  id: attachment.id,
                  type: "image",
                  name: attachment.name,
                  content_type: attachment.contentType,
                  content: [
                      { type: "image", image: attachment.dataUrl },
                  ],
              }
            : {
                  id: attachment.id,
                  type: "document",
                  name: attachment.name,
                  content_type: attachment.contentType,
                  content: [{ type: "text", text: attachment.text }],
              },
    );

    useChat.getState().setTodos(tabId, null);
    useChat.getState().appendUserMessage(
        tabId,
        text,
        undefined,
        attachments.map((attachment) =>
            attachment.kind === "image"
                ? {
                      kind: "image" as const,
                      uri: attachment.previewUri,
                      name: attachment.name,
                  }
                : { kind: "document" as const, name: attachment.name },
        ),
    );
    useChat.getState().startAssistant(tabId);
    if (attachments.length > 0) {
        useAttachments.getState().clear(tabId);
    }

    const isDraft = tab?.sessionId == null;
    const route = useRoute.getState();
    if (isDraft) {
        useChat.getState().setProjectId(tabId, route.projectId);
        // Consume the draft's project so the next new chat starts ungrouped,
        // as the web's switchToDraftThread does.
        useRoute.getState().setProjectId(null);
    }
    const selectedModel = isDraft
        ? useSessions
              .getState()
              .models.find((model) => model.id === route.modelId)
        : undefined;
    const sessionAgent = tab?.sessionId
        ? useSessions
              .getState()
              .items.find((item) => item.id === tab.sessionId)?.agent_key
        : undefined;
    const effort =
        isDraft &&
        route.reasoningEffort &&
        selectedModel?.efforts.includes(route.reasoningEffort)
            ? route.reasoningEffort
            : null;

    startStream({
        tabId,
        // A tab restored from disk has a session id before its chat slice is
        // hydrated; sending must continue that session, not start a new one.
        sessionId: slice.sessionId ?? tab?.sessionId ?? null,
        message: text,
        provider: selectedModel?.provider,
        model: selectedModel?.model,
        agentKey: isDraft
            ? route.agentKey ?? undefined
            : slice.agentKey ?? sessionAgent ?? undefined,
        projectId: isDraft ? route.projectId : null,
        // Existing sessions keep their stored route; a global effort selected
        // for another model must not silently override it.
        reasoningEffort: isDraft ? effort : undefined,
        attachments: payload,
    });
}

/** Re-run the last answer without appending a user message. */
export function regenerateTurn(tabId: string): void {
    const slice = chatSlice(tabId);
    if (slice.streaming) {
        return;
    }
    const sessionId =
        slice.sessionId ??
        useTabs.getState().tabs.find((tab) => tab.id === tabId)?.sessionId ??
        null;
    if (!sessionId) {
        return;
    }
    useChat.getState().setTodos(tabId, null);
    useChat.getState().setError(tabId, null);
    useChat.getState().setStreaming(tabId, true);
    startStream({
        tabId,
        sessionId,
        message: "",
        regenerate: true,
    });
}

/** Reattach to a turn that is still running server-side. */
export async function resumeTurn(tabId: string): Promise<void> {
    const slice = chatSlice(tabId);
    if (!slice.sessionId || slice.streaming) {
        return;
    }
    const cursor = sequences.get(tabId);
    const status = await getStreamStatus(slice.sessionId).catch(() => null);
    if (!status) {
        return;
    }
    if (status.status === "done" && status.last_seq <= cursor) {
        return;
    }
    useChat.getState().startAssistant(tabId);
    startStream({
        tabId,
        sessionId: slice.sessionId,
        message: "",
        resumeFromSequence: cursor,
        resuming: true,
    });
}

export function abortTabStream(tabId: string): void {
    streams.get(tabId)?.close();
    streams.delete(tabId);
}

export function dropTabStream(tabId: string): void {
    abortTabStream(tabId);
    sequences.drop(tabId);
}

export async function approveTab(options: {
    tabId: string;
    approved: boolean;
    remember?: boolean;
}): Promise<void> {
    const slice = chatSlice(options.tabId);
    const approval = slice.approval;
    if (!approval || !slice.sessionId) {
        return;
    }
    const ok = await approveCommand({
        sessionId: slice.sessionId,
        requestId: approval.requestId,
        approved: options.approved,
        remember: options.remember ?? false,
    });
    useChat.getState().setApproval(options.tabId, null);
    useTabs.getState().setAttention(options.tabId, null);
    if (!ok) {
        useChat
            .getState()
            .setError(options.tabId, "That approval is no longer pending");
    }
}

/** The turn has already returned its questions; drop any lingering reader. */
function settleBeforeAnswer(tabId: string): void {
    if (chatSlice(tabId).streaming) {
        abortTabStream(tabId);
        useChat.getState().finishTurn(tabId);
    }
}

export function submitAskAnswers(
    tabId: string,
    answers: Readonly<Record<string, string>>,
): void {
    const slice = chatSlice(tabId);
    const questions = slice.ask;
    if (!questions || questions.length === 0) {
        return;
    }
    settleBeforeAnswer(tabId);
    const text = formatAskAnswers(questions, answers);
    useChat.getState().setAsk(tabId, null);
    useChat.getState().setRequiresInput(tabId, null);
    useTabs.getState().setAttention(tabId, null);
    runTurn(tabId, text);
}

export function cancelAsk(tabId: string): void {
    const slice = chatSlice(tabId);
    const questions = slice.ask;
    if (!questions || questions.length === 0) {
        return;
    }
    settleBeforeAnswer(tabId);
    const text = cancelAskText(questions);
    useChat.getState().setAsk(tabId, null);
    useChat.getState().setRequiresInput(tabId, null);
    useTabs.getState().setAttention(tabId, null);
    runTurn(tabId, text);
}

export async function interruptTab(tabId: string): Promise<void> {
    const slice = chatSlice(tabId);
    if (!slice.sessionId) {
        abortTabStream(tabId);
        useChat.getState().finishTurn(tabId);
        return;
    }
    const interrupted = await interruptChat(slice.sessionId);
    if (!interrupted) {
        abortTabStream(tabId);
        useChat.getState().finishTurn(tabId);
    }
}

export function hasLocalStream(tabId: string): boolean {
    return streams.has(tabId);
}

export function resetStreams(): void {
    for (const handle of streams.values()) {
        handle.close();
    }
    streams.clear();
    sequences.clear();
}
