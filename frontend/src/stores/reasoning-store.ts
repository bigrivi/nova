import { create } from "zustand";

interface ReasoningStore {
    compacting: boolean;
    setCompacting: (compacting: boolean) => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
    compacting: false,
    setCompacting: (compacting) => set({ compacting }),
}));
