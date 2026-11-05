/** Session tabs for the app, wrapping the pure transitions in `src/tabs`. */
import { create } from "zustand";

import {
    adoptSession,
    closeTab,
    createTab,
    cycleTab,
    hydrateTabs,
    initialTabsState,
    markTurnEnded,
    removeTabs,
    renameTab,
    reopenTab,
    selectTab,
    setAttention,
    setFocused,
    setTitleBySession,
    type SessionTab,
    type TabAttention,
    type TabsState,
} from "../tabs/tab-state";

type TabsStore = TabsState & {
    hydrate: (
        entries: readonly { sessionId: string; title?: string }[],
        activeSessionId?: string | null,
    ) => void;
    createDraft: () => SessionTab;
    createSession: (sessionId: string, title?: string) => SessionTab;
    select: (id: string) => void;
    close: (id?: string) => string | null;
    reopen: () => SessionTab | null;
    adopt: (tabId: string, sessionId: string) => void;
    setTitle: (sessionId: string, title: string) => void;
    rename: (tabId: string, title: string) => void;
    remove: (ids: readonly string[]) => void;
    markTurnEnded: (tabId: string, ok: boolean) => void;
    setAttention: (tabId: string, attention: TabAttention | null) => void;
    setFocused: (focused: boolean) => void;
    cycle: (offset: 1 | -1) => void;
    reset: () => void;
};

export const useTabs = create<TabsStore>((set, get) => ({
    ...initialTabsState(),

    hydrate: (entries, activeSessionId = null) =>
        set(hydrateTabs(get(), entries, activeSessionId)),

    createDraft: () => {
        const { state, tab } = createTab(get());
        set(selectTab(state, tab.id));
        return tab;
    },

    createSession: (sessionId, title) => {
        const { state, tab } = createTab(get(), { sessionId, title });
        set(selectTab(state, tab.id));
        return tab;
    },

    select: (id) => set(selectTab(get(), id)),

    close: (id) => {
        const { state, nextId } = closeTab(get(), id);
        set(state);
        return nextId;
    },

    reopen: () => {
        const { state, tab } = reopenTab(get());
        set(state);
        return tab;
    },

    adopt: (tabId, sessionId) => set(adoptSession(get(), tabId, sessionId)),

    setTitle: (sessionId, title) =>
        set(setTitleBySession(get(), sessionId, title)),

    rename: (tabId, title) => set(renameTab(get(), tabId, title)),

    remove: (ids) => set(removeTabs(get(), ids)),

    markTurnEnded: (tabId, ok) => set(markTurnEnded(get(), tabId, ok)),

    setAttention: (tabId, attention) =>
        set(setAttention(get(), tabId, attention)),

    setFocused: (focused) => set(setFocused(get(), focused)),

    cycle: (offset) => set(cycleTab(get(), offset)),

    reset: () => set(initialTabsState()),
}));

export function activeTab(): SessionTab | null {
    const state = useTabs.getState();
    return state.tabs.find((tab) => tab.id === state.activeId) ?? null;
}

export function tabForSession(sessionId: string): SessionTab | null {
    return (
        useTabs
            .getState()
            .tabs.find((tab) => tab.sessionId === sessionId) ?? null
    );
}
