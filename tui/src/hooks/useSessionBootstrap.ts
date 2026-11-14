/** Startup session sync: titles, agents, pending badges, and the last tab.
 *
 *  The session list is fetched once on launch. The same fetch drops restored
 *  tabs whose session is gone and refreshes their titles from the backend.
 */
import { useRef } from "react";

import { listPendingSessions, listSessions } from "../api/nova-api.ts";
import type {
    NovaPendingSummary,
    NovaSessionSummary,
} from "../api/types.ts";
import {
    pruneRestoredTabs,
} from "../lib/tab-persistence.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";
import { useAsyncOnMount } from "./useAsyncOnMount.ts";

/** Refresh the titles of the tabs that point at a known session. */
export function syncSessionTitles(sessions: NovaSessionSummary[]): void {
    const store = useTabStore.getState();
    for (const session of sessions) {
        if (session.title) {
            store.setTitle(session.id, session.title);
        }
    }
}

/** Restore the agent of the tabs that were already open at startup. */
export function syncAgentsFromSessions(
    sessions: NovaSessionSummary[],
    startupTabIds: Set<string>,
): void {
    const store = useTabStore.getState();
    for (const session of sessions) {
        const tab = store.tabs.find((item) => item.sessionId === session.id);
        if (tab && startupTabIds.has(tab.id) && session.agent_key) {
            useChatStore
                .getState()
                .setAgent(session.agent_key, session.agent_key, tab.id);
        }
    }
}

/** Badge the tabs that are waiting for a question or an approval.
 *
 *  Restored tabs carry the badge before they are opened; the dialog itself
 *  waits until the tab is selected.
 */
export function applyPendingAttention(pending: NovaPendingSummary): void {
    for (const tab of useTabStore.getState().tabs) {
        if (!tab.sessionId) continue;
        const prompt = pending[tab.sessionId];
        if (!prompt) continue;
        useTabStore
            .getState()
            .setAttention(
                tab.id,
                prompt.ask ? "question" : prompt.approvals > 0 ? "approval" : null,
            );
    }
}

/** Load the session list on launch and fold it into the tab store. */
export function useSessionBootstrap(
    onSavedSessions: (count: number) => void,
): void {
    const countRef = useRef(onSavedSessions);
    countRef.current = onSavedSessions;

    useAsyncOnMount(
        () => {
            // Snapshot before the request: a tab opened while the fetch is in
            // flight is not a startup tab and must not inherit an agent.
            const startupTabIds = new Set(
                useTabStore.getState().tabs.map((tab) => tab.id),
            );
            return Promise.all([
                listSessions({ workspaceDir: WORKSPACE_DIR }),
                // Pending prompts are a decoration: a backend that cannot list
                // them must not keep the app from starting.
                listPendingSessions().catch((): NovaPendingSummary => ({})),
            ]).then(([sessions, pending]) => ({
                sessions,
                pending,
                startupTabIds,
            }));
        },
        ({ sessions, pending, startupTabIds }) => {
            countRef.current(sessions.length);
            pruneRestoredTabs(new Set(sessions.map((session) => session.id)));
            syncSessionTitles(sessions);
            syncAgentsFromSessions(sessions, startupTabIds);
            applyPendingAttention(pending);
        },
    );
}
