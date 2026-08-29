/** Compaction progress: mirrors the backend's COMPACTION_START/END events */

import { create } from "zustand";

export type CompactionState = {
    compacting: boolean;
    messageCount: number;
    tokenCount: number;
    startedAt: number | null;
    start: (messageCount: number, tokenCount: number) => void;
    end: () => void;
};

export const useCompactionStore = create<CompactionState>((set) => ({
    compacting: false,
    messageCount: 0,
    tokenCount: 0,
    startedAt: null,
    start: (messageCount, tokenCount) =>
        set({
            compacting: true,
            messageCount,
            tokenCount,
            startedAt: Date.now(),
        }),
    end: () =>
        set({
            compacting: false,
            messageCount: 0,
            tokenCount: 0,
            startedAt: null,
        }),
}));
