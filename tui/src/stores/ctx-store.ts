/** Context window usage: same numbers the backend compaction uses */

import { create } from "zustand";

export type CtxState = {
    used: number;
    limit: number;
    percent: number;
    setCtx: (used: number, limit: number, percent?: number) => void;
    clear: () => void;
};

export const useCtxStore = create<CtxState>((set) => ({
    used: 0,
    limit: 0,
    percent: 0,
    setCtx: (used, limit, percent) =>
        set({
            used,
            limit,
            percent:
                percent ??
                (limit ? Math.min(100, Math.round((used / limit) * 100)) : 0),
        }),
    clear: () => set({ used: 0, limit: 0, percent: 0 }),
}));
