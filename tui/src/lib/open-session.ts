/** Open a saved session in a tab: fetch its history and show it.
 *
 *  Shared by the sessions list and `/fork`, so the two cannot drift on what
 *  "open a session" means (which ids get reset, what happens on failure).
 *
 *  Opening is a read. It restores the agent and the route the conversation ran
 *  with into the tab, and must not write either back: a pick is the only
 *  thing that changes defaults, and a send is the only thing that changes a
 *  session's recorded route.
 */
import {
    getAgent,
    getChatStreamStatus,
    getSessionPending,
    getSessionRoute,
    listMessages,
} from "../api/nova-api.ts";
import { chatSlice, useChatStore, type TuiMessage } from "../stores/chat-store.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { NEW_TAB_TITLE, useTabStore } from "../stores/tab-store.ts";
import { parseAskQuestions } from "../stream/apply-event.ts";
import { truncateEnd } from "./display-width.ts";
import { ensureSessionTab, markTabLoaded, selectTab } from "./tab-actions.ts";
import { resumeChatStream } from "../stream/chat-stream.ts";
import { recordsToMessages } from "../utils/history.ts";

/** First user line, flattened, as the tab title until the server names it. */
function titleFromMessages(messages: TuiMessage[]): string | null {
    const firstUser = messages.find((message) => message.role === "user");
    const text = firstUser?.parts
        .filter((part) => part.type === "text")
        .map((part) => (part.type === "text" ? part.text : ""))
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
    return text ? truncateEnd(text, 40) : null;
}

/** Prompts the server is still waiting on, independent of the live stream. */
async function applyPendingPrompts(
    sessionId: string,
    tabId: string,
): Promise<void> {
    const pending = await getSessionPending(sessionId).catch(() => null);
    if (!pending) {
        return;
    }
    const approvals = pending.approvals ?? [];
    useApprovalStore
        .getState()
        .dropFetched(
            sessionId,
            new Set(approvals.map((approval) => approval.requestId)),
        );
    for (const approval of approvals) {
        useApprovalStore.getState().setPending({ ...approval, runId: -1 });
    }
    if (approvals.length > 0) {
        useTabStore.getState().setAttention(tabId, "approval");
    }
    // The endpoint is authoritative; replace any recovered form for this tab.
    useAskUserStore.getState().clearTab(tabId);
    if (pending.ask && pending.ask.length > 0) {
        const questions = parseAskQuestions({ questions: pending.ask });
        if (questions.length > 0) {
            useAskUserStore.getState().setActive(questions, tabId);
            useTabStore.getState().setAttention(tabId, "question");
        }
    }
}

/** Load *sessionId* into a tab, creating one when *tabId* is omitted. Throws when the fetch fails. */
export async function openSession(
    sessionId: string,
    agentKey?: string | null,
    tabId?: string,
    title?: string | null,
): Promise<void> {
    const tab = tabId
        ? { id: tabId }
        : ensureSessionTab(sessionId, title ?? undefined);

    // The stream may be gone (tab closed, process restarted); the server still
    // knows which prompts it is waiting on. Fetch them before the transcript so
    // the dialog appears even if the replay buffer lost the frame.
    await applyPendingPrompts(sessionId, tab.id);

    // A tab that is already streaming must not be reloaded from history: the
    // live turn's message ids would stop matching the fetched transcript.
    if (chatSlice(tab.id).isStreaming) {
        markTabLoaded(tab.id);
        if (!tabId) {
            selectTab(tab.id);
        }
        return;
    }

    // A history fetch that overlaps a turn must not replace the live
    // transcript; the stream's messages are authoritative.
    const baseline = chatSlice(tab.id).messages.length;
    const records = await listMessages(sessionId);
    if (
        chatSlice(tab.id).isStreaming ||
        chatSlice(tab.id).messages.length > baseline
    ) {
        markTabLoaded(tab.id);
        if (!tabId) {
            selectTab(tab.id);
        }
        return;
    }
    const messages = recordsToMessages(records);
    useChatStore
        .getState()
        .loadHistory(sessionId, messages, tab.id);

    const fallbackTitle = title ?? titleFromMessages(messages);
    const current = useTabStore
        .getState()
        .tabs.find((item) => item.id === tab.id);
    if (fallbackTitle && current?.title === NEW_TAB_TITLE) {
        useTabStore.getState().setTitle(sessionId, fallbackTitle);
    }

    if (agentKey && agentKey !== chatSlice(tab.id).agentKey) {
        // The conversation belongs to an agent; continuing it under whichever
        // agent happens to be selected would change its prompt and tools.
        const agent = await getAgent(agentKey);
        useChatStore
            .getState()
            .setAgent(agentKey, agent?.name ?? agentKey, tab.id);
    }

    const route = await getSessionRoute(sessionId);
    if (route?.provider && route.model) {
        useChatStore.getState().setRoute(
            {
                provider: route.provider,
                model: route.model,
                reasoningEffort: route.reasoning_effort ?? "",
            },
            tab.id,
        );
    }

    markTabLoaded(tab.id);
    if (!tabId) {
        selectTab(tab.id);
    }

    // Reopening a session whose turn is still running must reattach: the replay
    // carries a pending approval back into the dialog and then live-tails.
    if (!chatSlice(tab.id).isStreaming) {
        const status = await getChatStreamStatus(sessionId).catch(() => null);
        if (
            status &&
            (status.status === "active" || status.status === "detached") &&
            useTabStore.getState().tabs.some((item) => item.id === tab.id)
        ) {
            void resumeChatStream(sessionId);
        }
    }
}
