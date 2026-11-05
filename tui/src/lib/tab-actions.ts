/** Tab switch helpers that keep the tab store and the chat store in lockstep.
 *
 *  The tab store owns the active id; the chat store owns the active transcript.
 *  Keeping that sequence in one place is what stops a switch from overwriting
 *  the wrong slice.
 */
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import {
    activeTab,
    tabForSession,
    useTabStore,
    type SessionTab,
} from "../stores/tab-store.ts";
import { chatSlice } from "../stores/chat-store.ts";
import { abortTabStream } from "../stream/chat-stream.ts";

/** Tabs whose history is being fetched, and tabs that have fetched it once. */
const loadingTabs = new Set<string>();
const loadedTabs = new Set<string>();

/** Load a restored tab's history the first time it is opened. */
function ensureLoaded(tab: SessionTab): void {
    if (!tab.sessionId || loadedTabs.has(tab.id) || loadingTabs.has(tab.id)) {
        return;
    }
    const slice = chatSlice(tab.id);
    if (slice.messages.length > 0 || slice.isStreaming) {
        return;
    }
    loadingTabs.add(tab.id);
    void import("./open-session.ts")
        .then(({ openSession }) =>
            openSession(tab.sessionId!, undefined, tab.id),
        )
        .then(() => loadedTabs.add(tab.id))
        .catch(() => {})
        .finally(() => loadingTabs.delete(tab.id));
}

/** Mark a tab whose history was loaded by another entry point. */
export function markTabLoaded(id: string): void {
    loadedTabs.add(id);
}

export function selectTab(id: string): void {
    const store = useTabStore.getState();
    const tab = store.tabs.find((item) => item.id === id);
    if (!tab) {
        return;
    }
    if (store.activeId === id) {
        store.clearUnread(id);
        ensureLoaded(tab);
        return;
    }
    const previous = store.activeId;
    useChatStore.getState().activate(id, previous);
    store.select(id);
    useCtxStore.getState().clear();
    ensureLoaded(tab);
}

export function selectTabIndex(index: number): void {
    const tab = useTabStore.getState().tabs[index];
    if (tab) {
        selectTab(tab.id);
    }
}

export function cycleTabs(offset: 1 | -1): void {
    const store = useTabStore.getState();
    const tabs = store.tabs;
    if (tabs.length === 0) {
        return;
    }
    const index = tabs.findIndex((tab) => tab.id === store.activeId);
    const start = index === -1 ? (offset === 1 ? -1 : 0) : index;
    const next = tabs[(start + offset + tabs.length * 2) % tabs.length];
    if (next) {
        selectTab(next.id);
    }
}

export function openDraftTab(): string {
    const current = activeTab();
    if (current && current.sessionId === null) {
        return current.id;
    }
    const tab = useTabStore.getState().create();
    selectTab(tab.id);
    return tab.id;
}

/** Find or create the tab for a session without selecting it yet.
 *
 *  The caller loads history into the returned tab first, so switching never
 *  flashes an empty transcript.
 */
export function ensureSessionTab(
    sessionId: string,
    title?: string,
): SessionTab {
    const existing = tabForSession(sessionId);
    if (existing) {
        return existing;
    }
    return useTabStore.getState().create({ sessionId, title });
}

export function closeTab(id?: string): void {
    const store = useTabStore.getState();
    const target = id ?? store.activeId;
    if (!target) {
        return;
    }
    const tab = store.tabs.find((item) => item.id === target);
    const sessionId = tab?.sessionId ?? chatSlice(target).sessionId;
    // Closing hides the tab and ends this client's reader. The server keeps the
    // turn alive (detached); reopening the session replays the buffered frames,
    // which is how a pending approval reappears.
    abortTabStream(target);
    loadingTabs.delete(target);
    loadedTabs.delete(target);
    useTabStore.getState().setAttention(target, null);
    if (sessionId) {
        useApprovalStore.getState().clearSession(sessionId);
    }
    useAskUserStore.getState().clearTab(target);
    const previous = store.activeId;
    const next = store.close(target);
    useChatStore.getState().remove(target);
    if (next && next !== previous) {
        useChatStore.getState().activate(next, null);
        useTabStore.getState().select(next);
        useCtxStore.getState().clear();
    } else if (next === null) {
        useChatStore.getState().activate(null, null);
        useCtxStore.getState().clear();
    }
}

/** Reopen the most recently closed tab, restoring its view. */
export function reopenLastClosed(): string | null {
    const store = useTabStore.getState();
    const previous = store.activeId;
    const tab = store.reopen();
    if (!tab) {
        return null;
    }
    useChatStore.getState().activate(tab.id, previous);
    useTabStore.getState().select(tab.id);
    ensureLoaded(tab);
    return tab.id;
}

/** Bring the tab that owns *sessionId* forward, if it is open. */
export function focusSession(sessionId: string): void {
    const tab = tabForSession(sessionId);
    if (tab && useTabStore.getState().activeId !== tab.id) {
        selectTab(tab.id);
    }
}
