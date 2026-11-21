/** Token and cost totals per session, so a tab switch reads instead of fetches. */

import { create } from "zustand";
import type { NovaStats } from "../api/types.ts";

type UsageState = {
    byId: Record<string, NovaStats>;
    setStats: (sessionId: string, stats: NovaStats) => void;
    clear: (sessionId?: string) => void;
};

export const useUsageStore = create<UsageState>((set) => ({
    byId: {},
    setStats: (sessionId, stats) =>
        set((state) => ({ byId: { ...state.byId, [sessionId]: stats } })),
    clear: (sessionId) =>
        set((state) => {
            if (sessionId === undefined) {
                return { byId: {} };
            }
            if (!(sessionId in state.byId)) {
                return state;
            }
            const byId = { ...state.byId };
            delete byId[sessionId];
            return { byId };
        }),
}));

/** The spend for one session; null until it has been read once. */
export function useSessionStats(sessionId: string | null): NovaStats | null {
    return useUsageStore((state) =>
        sessionId === null ? null : (state.byId[sessionId] ?? null),
    );
}
