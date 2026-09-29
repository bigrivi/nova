import { create } from "zustand";

export type ContextUsage = {
    used: number;
    limit: number;
    percent: number;
};

type ContextUsageStore = {
    bySession: Record<string, ContextUsage>;
    setForSession: (sessionId: string, usage: ContextUsage) => void;
    clearSession: (sessionId: string) => void;
};

/**
 * Per-session context-window usage. Written from two sources that share the
 * same backend numbers: the REST context endpoint on thread open, and the
 * `data-nova-context` SSE frames while streaming. Keyed by session id so a
 * background thread can never overwrite the visible pill.
 */
export const useContextUsageStore = create<ContextUsageStore>((set) => ({
    bySession: {},
    setForSession: (sessionId, usage) =>
        set((state) => ({
            bySession: { ...state.bySession, [sessionId]: usage },
        })),
    clearSession: (sessionId) =>
        set((state) => {
            if (!(sessionId in state.bySession)) {
                return state;
            }
            const next = { ...state.bySession };
            delete next[sessionId];
            return { bySession: next };
        }),
}));
