import { create } from "zustand";

/**
 * The retry currently in flight.
 *
 * `attempt` is the attempt that just failed, not the one about to be made, so
 * "attempt 2" reads as "the second try did not work" rather than as a count of
 * tries remaining.
 */
export type RetryState = {
    attempt: number;
    total: number;
    reason: string;
};

interface ReasoningStore {
    compacting: boolean;
    /** The summary as it is written, so the user can watch compaction happen. */
    compactionSummary: string;
    /**
     * Set while the provider is waiting to re-send a request, cleared when the
     * stream moves on. The line describes a wait that is happening, so it has
     * to be cleared by the same stream that set it rather than by a timer.
     */
    retry: RetryState | null;
    setCompacting: (compacting: boolean) => void;
    appendCompactionDelta: (delta: string) => void;
    setRetry: (retry: RetryState | null) => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
    compacting: false,
    compactionSummary: "",
    retry: null,
    // Starting a compaction clears the previous run's text; finishing keeps it
    // (the banner is hidden once compacting is false, and the durable copy is
    // the summary message the backend already writes).
    setCompacting: (compacting) =>
        set(compacting ? { compacting, compactionSummary: "" } : { compacting }),
    appendCompactionDelta: (delta) =>
        set((state) => ({
            compactionSummary: state.compactionSummary + delta,
        })),
    setRetry: (retry) => set({ retry }),
}));
