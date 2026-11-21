/** Context window usage: same numbers the backend compaction uses, per session. */

import { create } from "zustand";

export type CtxSnapshot = {
    used: number;
    limit: number;
    percent: number;
};

export type CtxState = {
    byId: Record<string, CtxSnapshot>;
    setCtx: (
        sessionId: string,
        used: number,
        limit: number,
        percent?: number,
    ) => void;
    clear: (sessionId?: string) => void;
};

const NO_CTX: CtxSnapshot = { used: 0, limit: 0, percent: 0 };

export const useCtxStore = create<CtxState>((set) => ({
    byId: {},
    setCtx: (sessionId, used, limit, percent) =>
        set((state) => ({
            byId: {
                ...state.byId,
                [sessionId]: {
                    used,
                    limit,
                    percent:
                        percent ??
                        (limit ? Math.round((used / limit) * 100) : 0),
                },
            },
        })),
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

/** One session's meter; switching sessions swaps the numbers, not the block. */
export function useCtx(sessionId: string | null): CtxSnapshot {
    return useCtxStore((state) =>
        sessionId === null ? NO_CTX : (state.byId[sessionId] ?? NO_CTX),
    );
}
