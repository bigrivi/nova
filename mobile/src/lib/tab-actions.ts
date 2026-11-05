/** Keep the tab store, chat store, history fetch and stream registry in step. */
import {
    getSessionPending,
    getSessionRoute,
    getStreamStatus,
    listMessages,
} from "../api/client";
import type { ApprovalRequest } from "../api/types";
import { parseAskQuestions } from "../chat/ask";
import { useAttachments } from "../state/attachments";
import { useChat, chatSlice } from "../state/chat";
import { useDrafts } from "../state/drafts";
import { useTabs, tabForSession } from "../state/tabs";
import { useSessions } from "../state/sessions";
import { recordsToMessages } from "./history";
import {
    dropTabStream,
    hasLocalStream,
    resumeTurn,
} from "./stream-runner";

const loading = new Set<string>();
const loaded = new Set<string>();

export function resetLoadedTabs(): void {
    loading.clear();
    loaded.clear();
}

function applyPending(tabId: string, sessionId: string): Promise<void> {
    return getSessionPending(sessionId)
        .then((pending) => {
            const approvals = pending.approvals ?? [];
            if (approvals.length > 0) {
                const approval = approvals[0] as ApprovalRequest;
                useChat.getState().setApproval(tabId, approval);
                useTabs.getState().setAttention(tabId, "approval");
            }
            if (pending.ask && pending.ask.length > 0) {
                const questions = parseAskQuestions({
                    questions: pending.ask,
                });
                if (questions.length > 0) {
                    useChat.getState().setAsk(tabId, questions);
                }
                useChat
                    .getState()
                    .setRequiresInput(
                        tabId,
                        "The agent is waiting for an answer",
                    );
                useTabs.getState().setAttention(tabId, "question");
            }
        })
        .catch(() => {
            // A pending lookup is an optimization; the live stream still wins.
        });
}

/** Load history once, then reattach if the server still has the turn. */
export async function ensureLoaded(tabId: string): Promise<void> {
    const tab = useTabs.getState().tabs.find((item) => item.id === tabId);
    if (!tab?.sessionId || loaded.has(tabId) || loading.has(tabId)) {
        return;
    }
    if (chatSlice(tabId).streaming) {
        loaded.add(tabId);
        return;
    }
    loading.add(tabId);
    try {
        await applyPending(tabId, tab.sessionId);
        const [records, route] = await Promise.all([
            listMessages(tab.sessionId),
            getSessionRoute(tab.sessionId).catch(() => null),
        ]);
        if (!chatSlice(tabId).streaming) {
            useChat
                .getState()
                .loadHistory(tabId, tab.sessionId, recordsToMessages(records));
        }
        if (route) {
            const model = useSessions
                .getState()
                .models.find(
                    (entry) =>
                        entry.provider === route.provider &&
                        entry.model === route.model,
                );
            useChat.getState().setModel(tabId, model?.id ?? null);
            useChat.getState().setEffort(tabId, route.reasoning_effort);
        }
        loaded.add(tabId);

        const status = await getStreamStatus(tab.sessionId).catch(() => null);
        if (
            status &&
            (status.status === "active" || status.status === "detached")
        ) {
            await resumeTurn(tabId);
        }
    } catch (error) {
        useChat
            .getState()
            .setError(
                tabId,
                error instanceof Error
                    ? error.message
                    : "Could not load the conversation",
            );
    } finally {
        loading.delete(tabId);
    }
}

export function markLoaded(tabId: string): void {
    loaded.add(tabId);
}

export function selectTab(tabId: string): void {
    useTabs.getState().select(tabId);
    void ensureLoaded(tabId);
}

export function openDraftTab(): string {
    const state = useTabs.getState();
    const active = state.tabs.find((tab) => tab.id === state.activeId);
    if (active && active.sessionId === null) {
        selectTab(active.id);
        return active.id;
    }
    const tab = useTabs.getState().createDraft();
    return tab.id;
}

export function openSessionTab(
    sessionId: string,
    title?: string | null,
    agentKey?: string | null,
    projectId?: string | null,
): string {
    const existing = tabForSession(sessionId);
    if (existing) {
        if (agentKey) {
            useChat.getState().setAgent(existing.id, agentKey);
        }
        if (projectId !== undefined) {
            useChat.getState().setProjectId(existing.id, projectId);
        }
        selectTab(existing.id);
        return existing.id;
    }
    const tab = useTabs
        .getState()
        .createSession(sessionId, title ?? undefined);
    if (agentKey) {
        useChat.getState().setAgent(tab.id, agentKey);
    }
    if (projectId !== undefined) {
        useChat.getState().setProjectId(tab.id, projectId);
    }
    void ensureLoaded(tab.id);
    return tab.id;
}

export function closeTab(tabId?: string): string | null {
    const state = useTabs.getState();
    const target = tabId ?? state.activeId;
    if (!target) {
        return null;
    }
    const tab = state.tabs.find((item) => item.id === target);
    if (tab?.attention) {
        useTabs.getState().setAttention(target, null);
    }
    abortForTab(target);
    useChat.getState().remove(target);
    useDrafts.getState().clear(target);
    useAttachments.getState().clear(target);
    loaded.delete(target);
    loading.delete(target);
    const nextId = useTabs.getState().close(target);
    if (nextId) {
        selectTab(nextId);
    }
    return nextId;
}

function abortForTab(tabId: string): void {
    dropTabStream(tabId);
}

export function reopenLastClosed(): string | null {
    const tab = useTabs.getState().reopen();
    if (!tab) {
        return null;
    }
    void ensureLoaded(tab.id);
    return tab.id;
}

/** Used by session events: focus the tab that owns *sessionId*. */
export function focusSession(sessionId: string): string | null {
    const tab = tabForSession(sessionId);
    if (!tab) {
        return null;
    }
    selectTab(tab.id);
    return tab.id;
}

/** A tab whose stream exists locally should not be re-tailed by an event. */
export function tabIsStreaming(tabId: string): boolean {
    return hasLocalStream(tabId);
}
