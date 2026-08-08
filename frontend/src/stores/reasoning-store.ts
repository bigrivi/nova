import { create } from "zustand";

interface ReasoningStore {
  chainStartTime: number | null;
  compacting: boolean;
  setChainStartTime: (t: number | null) => void;
  setCompacting: (compacting: boolean) => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
  chainStartTime: null,
  compacting: false,
  setChainStartTime: (t) => set({ chainStartTime: t }),
  setCompacting: (compacting) => set({ compacting }),
}));
