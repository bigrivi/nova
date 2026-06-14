import { create } from "zustand";

interface ReasoningStore {
  isActive: boolean;
  elapsedMs: number | null;
  chainActive: boolean;
  chainStartTime: number | null;
  chainElapsedMs: number | null;
  compacting: boolean;
  setActive: (active: boolean) => void;
  setElapsedMs: (ms: number | null) => void;
  setChainActive: (active: boolean) => void;
  setChainStartTime: (t: number | null) => void;
  setChainElapsedMs: (ms: number | null) => void;
  setCompacting: (compacting: boolean) => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
  isActive: false,
  elapsedMs: null,
  chainActive: false,
  chainStartTime: null,
  chainElapsedMs: null,
  compacting: false,
  setActive: (active) => set({ isActive: active }),
  setElapsedMs: (ms) => set({ elapsedMs: ms }),
  setChainActive: (active) => set({ chainActive: active }),
  setChainStartTime: (t) => set({ chainStartTime: t }),
  setChainElapsedMs: (ms) => set({ chainElapsedMs: ms }),
  setCompacting: (compacting) => set({ compacting }),
}));
