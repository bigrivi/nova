/** Server-side conversation list and the route options the composer needs. */
import { create } from "zustand";

import {
    deleteSession,
    listAgents,
    listModels,
    listSessions,
    renameSession,
    setSessionPinned,
} from "../api/client";
import type {
    NovaAgent,
    NovaModelRecord,
    NovaSessionSummary,
} from "../api/types";
import { useTabs } from "./tabs";

type SessionsState = {
    items: NovaSessionSummary[];
    models: NovaModelRecord[];
    agents: NovaAgent[];
    loading: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    updateTitle: (sessionId: string, title: string) => void;
    rename: (sessionId: string, title: string) => Promise<void>;
    setPinned: (sessionId: string, pinned: boolean) => Promise<void>;
    deleteRemote: (sessionId: string) => Promise<void>;
    removeLocal: (sessionId: string) => void;
    reset: () => void;
};

export const useSessions = create<SessionsState>((set) => ({
    items: [],
    models: [],
    agents: [],
    loading: false,
    error: null,

    refresh: async () => {
        set({ loading: true, error: null });
        try {
            const [items, models, agents] = await Promise.all([
                listSessions(),
                listModels().catch(() => [] as NovaModelRecord[]),
                listAgents().catch(() => [] as NovaAgent[]),
            ]);
            set({ items, models, agents, loading: false });
        } catch (error) {
            set({
                loading: false,
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not load sessions",
            });
        }
    },

    updateTitle: (sessionId, title) =>
        set((state) => ({
            items: state.items.map((item) =>
                item.id === sessionId ? { ...item, title } : item,
            ),
        })),

    rename: async (sessionId, title) => {
        await renameSession(sessionId, title);
        useTabs.getState().setTitle(sessionId, title);
        set((state) => ({
            items: state.items.map((item) =>
                item.id === sessionId ? { ...item, title } : item,
            ),
        }));
    },

    setPinned: async (sessionId, pinned) => {
        await setSessionPinned(sessionId, pinned);
        set((state) => ({
            items: state.items.map((item) =>
                item.id === sessionId ? { ...item, pinned } : item,
            ),
        }));
    },

    deleteRemote: async (sessionId) => {
        await deleteSession(sessionId);
        set((state) => ({
            items: state.items.filter((item) => item.id !== sessionId),
        }));
    },

    removeLocal: (sessionId) =>
        set((state) => ({
            items: state.items.filter((item) => item.id !== sessionId),
        })),

    reset: () =>
        set({ items: [], models: [], agents: [], loading: false, error: null }),
}));
