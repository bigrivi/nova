import { create } from "zustand";

interface ReasoningStore {
    compacting: boolean;
    /** The summary as it is written, so the user can watch compaction happen. */
    compactionSummary: string;
    setCompacting: (compacting: boolean) => void;
    appendCompactionDelta: (delta: string) => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
    compacting: false,
    compactionSummary: "",
    // Starting a compaction clears the previous run's text; finishing keeps it
    // (the banner is hidden once compacting is false, and the durable copy is
    // the summary message the backend already writes).
    setCompacting: (compacting) =>
        set(compacting ? { compacting, compactionSummary: "" } : { compacting }),
    appendCompactionDelta: (delta) =>
        set((state) => ({
            compactionSummary: state.compactionSummary + delta,
        })),
}));
