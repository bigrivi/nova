/** Session tabs: stable tab identity, active selection, unread and attention state.
 *
 *  A tab id never changes, including when a draft tab learns its real session id
 *  from the first `data-nova-session` frame. The session id is just a field, so
 *  per-tab state can key on the tab id for the tab's whole lifetime.
 */
import { create } from "zustand";

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
};

/** Resume cursors are written on every frame, so they deliberately live
 *  outside the reactive tab objects: a streaming tab must not re-render the
 *  whole strip hundreds of times per turn. */
const sequences = new Map<string, number>();

export function tabSequence(id: string): number {
    return sequences.get(id) ?? 0;
}

export function setTabSequence(id: string, sequence: number): void {
    // Frames from a tab that was closed mid-turn still arrive; do not recreate
    // a cursor for a tab the strip no longer has.
    if (!useTabStore.getState().tabs.some((tab) => tab.id === id)) {
        return;
    }
    sequences.set(id, sequence);
}

export const NEW_TAB_TITLE = "New session";

const CLOSED_TAB_LIMIT = 25;

type ClosedTab = { tab: SessionTab; index: number };

type TabState = {
    tabs: SessionTab[];
    activeId: string | null;
    closed: ClosedTab[];
    /** Whether the terminal window owns focus; a blurred tab does not count as viewed. */
    focused: boolean;

    create: (options?: {
        sessionId?: string | null;
        title?: string;
    }) => SessionTab;
    select: (id: string) => void;
    close: (id?: string) => string | null;
    reopen: () => SessionTab | null;
    adopt: (id: string, sessionId: string) => void;
    setTitle: (sessionId: string, title: string) => void;
    renameTab: (id: string, title: string) => void;
    hydrate: (tabs: { sessionId: string; title?: string }[]) => void;
    removeTabs: (ids: string[]) => void;
    markTurnEnded: (id: string, ok: boolean) => void;
    clearUnread: (id: string) => void;
    setAttention: (id: string, attention: TabAttention | null) => void;
    setFocused: (focused: boolean) => void;
    cycle: (offset: 1 | -1) => void;
    reset: () => void;
};

function makeTabId(): string {
    return `tab_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const useTabStore = create<TabState>((set, get) => ({
    tabs: [],
    activeId: null,
    closed: [],
    focused: true,

    create: (options = {}) => {
        const tab: SessionTab = {
            id: makeTabId(),
            sessionId: options.sessionId ?? null,
            title: options.title ?? NEW_TAB_TITLE,
            unread: null,
            attention: null,
        };
        set((state) => ({ tabs: [...state.tabs, tab] }));
        return tab;
    },

    select: (id) =>
        set((state) => {
            if (!state.tabs.some((tab) => tab.id === id)) {
                return state;
            }
            return {
                activeId: id,
                tabs: state.tabs.map((tab) =>
                    tab.id === id ? { ...tab, unread: null } : tab,
                ),
            };
        }),

    close: (id) => {
        const state = get();
        const target = id ?? state.activeId;
        if (!target) return null;
        const index = state.tabs.findIndex((tab) => tab.id === target);
        if (index === -1) return null;
        const closedTab = state.tabs[index]!;
        const remaining = state.tabs.filter((tab) => tab.id !== target);
        sequences.delete(target);
        const nextId =
            state.activeId === target
                ? (remaining[index]?.id ?? remaining[index - 1]?.id ?? null)
                : state.activeId;
        set({
            tabs: remaining,
            activeId: nextId,
            closed: [
                ...state.closed.filter((entry) => entry.tab.id !== target),
                { tab: closedTab, index },
            ].slice(-CLOSED_TAB_LIMIT),
        });
        return nextId;
    },

    reopen: () => {
        const state = get();
        const entry = state.closed.at(-1);
        if (!entry) return null;
        const tab: SessionTab = { ...entry.tab, unread: null };
        set({
            tabs: [
                ...state.tabs.slice(0, entry.index),
                tab,
                ...state.tabs.slice(entry.index),
            ],
            closed: state.closed.slice(0, -1),
            activeId: tab.id,
        });
        return tab;
    },

    adopt: (id, sessionId) =>
        set((state) => ({
            tabs: state.tabs.map((tab) =>
                tab.id === id ? { ...tab, sessionId } : tab,
            ),
        })),

    setTitle: (sessionId, title) =>
        set((state) => ({
            tabs: state.tabs.map((tab) =>
                tab.sessionId === sessionId && tab.title !== title
                    ? { ...tab, title }
                    : tab,
            ),
        })),

    renameTab: (id, title) =>
        set((state) => ({
            tabs: state.tabs.map((tab) =>
                tab.id === id && tab.title !== title ? { ...tab, title } : tab,
            ),
        })),

    hydrate: (restored) =>
        set((state) => {
            // Only fill an empty store: a tab created before the restore landed
            // must not be clobbered.
            if (state.tabs.length > 0) {
                return state;
            }
            const seen = new Set<string>();
            const tabs: SessionTab[] = [];
            for (const entry of restored) {
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
                });
            }
            return { tabs, activeId: null };
        }),

    removeTabs: (ids) =>
        set((state) => {
            const drop = new Set(ids);
            const tabs = state.tabs.filter((tab) => !drop.has(tab.id));
            if (tabs.length === state.tabs.length) {
                return state;
            }
            for (const id of drop) {
                sequences.delete(id);
            }
            return {
                tabs,
                activeId: tabs.some((tab) => tab.id === state.activeId)
                    ? state.activeId
                    : null,
            };
        }),

    markTurnEnded: (id, ok) =>
        set((state) => {
            const tab = state.tabs.find((item) => item.id === id);
            if (!tab) return state;
            if (state.activeId === id && state.focused) return state;
            return {
                tabs: state.tabs.map((item) =>
                    item.id === id
                        ? { ...item, unread: ok ? "activity" : "error" }
                        : item,
                ),
            };
        }),

    clearUnread: (id) =>
        set((state) => ({
            tabs: state.tabs.map((tab) =>
                tab.id === id && tab.unread !== null
                    ? { ...tab, unread: null }
                    : tab,
            ),
        })),

    setAttention: (id, attention) =>
        set((state) => ({
            tabs: state.tabs.map((tab) =>
                tab.id === id && tab.attention !== attention
                    ? { ...tab, attention }
                    : tab,
            ),
        })),

    setFocused: (focused) =>
        set((state) => ({
            focused,
            tabs: focused
                ? state.tabs.map((tab) =>
                      tab.id === state.activeId && tab.unread !== null
                          ? { ...tab, unread: null }
                          : tab,
                  )
                : state.tabs,
        })),

    cycle: (offset) => {
        const state = get();
        if (state.tabs.length === 0) return;
        const index = state.tabs.findIndex((tab) => tab.id === state.activeId);
        const start = index === -1 ? (offset === 1 ? -1 : 0) : index;
        const next =
            state.tabs[
                (start + offset + state.tabs.length * 2) % state.tabs.length
            ];
        if (next) {
            get().select(next.id);
        }
    },

    reset: () => {
        sequences.clear();
        set({ tabs: [], activeId: null, closed: [], focused: true });
    },
}));

export function activeTab(): SessionTab | null {
    const state = useTabStore.getState();
    return state.tabs.find((tab) => tab.id === state.activeId) ?? null;
}

export function tabForSession(sessionId: string): SessionTab | null {
    return (
        useTabStore
            .getState()
            .tabs.find((tab) => tab.sessionId === sessionId) ?? null
    );
}
