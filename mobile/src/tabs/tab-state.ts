/** Session tabs for the mobile client, ported from the TUI tab store.
 *
 *  A tab id never changes, including when a draft tab learns its real session
 *  id from the first `data-nova-session` frame. Per-tab state keys on the tab id
 *  for the tab's whole lifetime, which is what lets a background stream keep
 *  writing while another tab is on screen.
 *
 *  These transitions are pure so the Zustand store in the app is a thin
 *  wrapper and every rule below is testable without React Native.
 *
 *  Reference: `tui/src/stores/tab-store.ts`, `tui/src/lib/tab-actions.ts`.
 */

export type TabUnread = "activity" | "error";
export type TabAttention = "approval" | "question";

export type SessionTab = {
    id: string;
    sessionId: string | null;
    title: string;
    /** Set when a turn ends while the tab is not being viewed. */
    unread: TabUnread | null;
    /** Set while the tab waits on the user. */
    attention: TabAttention | null;
    createdAt: number;
    /** Drives least-recently-viewed eviction when the app caps open tabs. */
    lastViewedAt: number;
};

export type ClosedTab = { tab: SessionTab; index: number };

export type TabsState = {
    tabs: SessionTab[];
    activeId: string | null;
    closed: ClosedTab[];
    /**
     * Foreground and chat screen focused. A blurred tab does not count as
     * viewed, so a completion there stays unread.
     */
    focused: boolean;
};

export const NEW_TAB_TITLE = "New session";
export const CLOSED_TAB_LIMIT = 25;

export function makeTabId(): string {
    return `tab_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function initialTabsState(): TabsState {
    return { tabs: [], activeId: null, closed: [], focused: true };
}

/** Add a tab without selecting it; callers own the tab/chat-store lockstep. */
export function createTab(
    state: TabsState,
    options: {
        id?: string;
        sessionId?: string | null;
        title?: string;
        now?: number;
    } = {},
): { state: TabsState; tab: SessionTab } {
    const now = options.now ?? Date.now();
    const tab: SessionTab = {
        id: options.id ?? makeTabId(),
        sessionId: options.sessionId ?? null,
        title: options.title ?? NEW_TAB_TITLE,
        unread: null,
        attention: null,
        createdAt: now,
        lastViewedAt: now,
    };
    return { state: { ...state, tabs: [...state.tabs, tab] }, tab };
}

/** Make *id* active and clear its unread marker. Unknown ids are a no-op. */
export function selectTab(
    state: TabsState,
    id: string,
    now: number = Date.now(),
): TabsState {
    if (!state.tabs.some((tab) => tab.id === id)) {
        return state;
    }
    return {
        ...state,
        activeId: id,
        tabs: state.tabs.map((tab) =>
            tab.id === id
                ? { ...tab, unread: null, lastViewedAt: now }
                : tab,
        ),
    };
}

/**
 * Remove a tab and push it onto the reopen stack.
 *
 * `nextId` is the id the chat store should activate: the right neighbour,
 * then the left one, then null. Closing a background tab leaves `activeId`
 * where it was.
 *
 * Closing detaches this client's reader; it must not interrupt the server
 * turn. The caller aborts the tab's stream and drops its sequence cursor.
 */
export function closeTab(
    state: TabsState,
    id?: string,
): { state: TabsState; nextId: string | null } {
    const target = id ?? state.activeId;
    if (!target) {
        return { state, nextId: null };
    }
    const index = state.tabs.findIndex((tab) => tab.id === target);
    if (index === -1) {
        return { state, nextId: state.activeId };
    }
    const closedTab = state.tabs[index]!;
    const remaining = state.tabs.filter((tab) => tab.id !== target);
    const nextId =
        state.activeId === target
            ? (remaining[index]?.id ?? remaining[index - 1]?.id ?? null)
            : state.activeId;

    return {
        nextId,
        state: {
            ...state,
            tabs: remaining,
            activeId: nextId,
            closed: [
                ...state.closed.filter((entry) => entry.tab.id !== target),
                { tab: closedTab, index },
            ].slice(-CLOSED_TAB_LIMIT),
        },
    };
}

/** Restore the most recently closed tab at its original position. */
export function reopenTab(
    state: TabsState,
    now: number = Date.now(),
): { state: TabsState; tab: SessionTab | null } {
    const entry = state.closed.at(-1);
    if (!entry) {
        return { state, tab: null };
    }
    const tab: SessionTab = {
        ...entry.tab,
        unread: null,
        lastViewedAt: now,
    };
    return {
        tab,
        state: {
            ...state,
            tabs: [
                ...state.tabs.slice(0, entry.index),
                tab,
                ...state.tabs.slice(entry.index),
            ],
            closed: state.closed.slice(0, -1),
            activeId: tab.id,
        },
    };
}

/** Record the server id a draft tab created on its first turn. */
export function adoptSession(
    state: TabsState,
    tabId: string,
    sessionId: string,
): TabsState {
    return {
        ...state,
        tabs: state.tabs.map((tab) =>
            tab.id === tabId ? { ...tab, sessionId } : tab,
        ),
    };
}

/** Update the tab showing *sessionId*; title frames address sessions, not tabs. */
export function setTitleBySession(
    state: TabsState,
    sessionId: string,
    title: string,
): TabsState {
    return {
        ...state,
        tabs: state.tabs.map((tab) =>
            tab.sessionId === sessionId && tab.title !== title
                ? { ...tab, title }
                : tab,
        ),
    };
}

export function renameTab(
    state: TabsState,
    tabId: string,
    title: string,
): TabsState {
    return {
        ...state,
        tabs: state.tabs.map((tab) =>
            tab.id === tabId && tab.title !== title ? { ...tab, title } : tab,
        ),
    };
}

/**
 * Fill an empty store from disk.
 *
 * Only fills an empty store: a tab created before the restore landed must not
 * be clobbered. Duplicate session ids collapse, drafts are never persisted so
 * they cannot come back, and *activeSessionId* is restored only when it names
 * a tab that actually exists.
 */
export function hydrateTabs(
    state: TabsState,
    entries: readonly { sessionId: string; title?: string }[],
    activeSessionId: string | null = null,
): TabsState {
    if (state.tabs.length > 0) {
        return state;
    }
    const seen = new Set<string>();
    const tabs: SessionTab[] = [];
    for (const entry of entries) {
        const sessionId = entry.sessionId?.trim();
        if (!sessionId || seen.has(sessionId)) {
            continue;
        }
        seen.add(sessionId);
        tabs.push({
            id: makeTabId(),
            sessionId,
            title: entry.title?.trim() || "Session",
            unread: null,
            attention: null,
            createdAt: 0,
            lastViewedAt: 0,
        });
    }
    const activeId =
        activeSessionId === null
            ? null
            : (tabs.find((tab) => tab.sessionId === activeSessionId)?.id ??
              null);
    return { ...state, tabs, activeId };
}

/** Drop tabs by id; a removed active tab leaves the selection empty. */
export function removeTabs(state: TabsState, ids: readonly string[]): TabsState {
    const drop = new Set(ids);
    const tabs = state.tabs.filter((tab) => !drop.has(tab.id));
    if (tabs.length === state.tabs.length) {
        return state;
    }
    return {
        ...state,
        tabs,
        activeId:
            state.activeId !== null && drop.has(state.activeId)
                ? null
                : state.activeId,
    };
}

/** Drop saved tabs whose session no longer exists; drafts are untouched. */
export function pruneToSessions(
    state: TabsState,
    validSessionIds: ReadonlySet<string>,
): TabsState {
    const dead = state.tabs
        .filter(
            (tab) =>
                tab.sessionId !== null && !validSessionIds.has(tab.sessionId),
        )
        .map((tab) => tab.id);
    return dead.length > 0 ? removeTabs(state, dead) : state;
}

/**
 * A turn ended on *tabId*.
 *
 * The active, focused tab is being watched, so it stays clean. Everything
 * else — a background tab, or the active tab while the app is backgrounded —
 * gets a completion marker. The caller sets `focused` from AppState.
 */
export function markTurnEnded(
    state: TabsState,
    tabId: string,
    ok: boolean,
): TabsState {
    if (!state.tabs.some((tab) => tab.id === tabId)) {
        return state;
    }
    if (state.activeId === tabId && state.focused) {
        return state;
    }
    return {
        ...state,
        tabs: state.tabs.map((tab) =>
            tab.id === tabId
                ? { ...tab, unread: ok ? "activity" : "error" }
                : tab,
        ),
    };
}

export function clearUnread(state: TabsState, tabId: string): TabsState {
    return {
        ...state,
        tabs: state.tabs.map((tab) =>
            tab.id === tabId && tab.unread !== null
                ? { ...tab, unread: null }
                : tab,
        ),
    };
}

export function setAttention(
    state: TabsState,
    tabId: string,
    attention: TabAttention | null,
): TabsState {
    return {
        ...state,
        tabs: state.tabs.map((tab) =>
            tab.id === tabId && tab.attention !== attention
                ? { ...tab, attention }
                : tab,
        ),
    };
}

/** Returning to the foreground clears the active tab's completion marker. */
export function setFocused(state: TabsState, focused: boolean): TabsState {
    if (state.focused === focused) {
        return state;
    }
    if (!focused) {
        return { ...state, focused };
    }
    return {
        ...state,
        focused,
        tabs: state.tabs.map((tab) =>
            tab.id === state.activeId && tab.unread !== null
                ? { ...tab, unread: null }
                : tab,
        ),
    };
}

/** Move the selection by one, wrapping at both ends. */
export function cycleTab(state: TabsState, offset: 1 | -1): TabsState {
    if (state.tabs.length === 0) {
        return state;
    }
    const index = state.tabs.findIndex((tab) => tab.id === state.activeId);
    const start = index === -1 ? (offset === 1 ? -1 : 0) : index;
    const next =
        state.tabs[(start + offset + state.tabs.length * 2) % state.tabs.length];
    return next ? selectTab(state, next.id) : state;
}

export function activeTab(state: TabsState): SessionTab | null {
    return state.tabs.find((tab) => tab.id === state.activeId) ?? null;
}

export function tabForSession(
    state: TabsState,
    sessionId: string,
): SessionTab | null {
    return state.tabs.find((tab) => tab.sessionId === sessionId) ?? null;
}
