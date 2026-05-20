import { create } from "zustand";

interface ReasoningStore {
  isActive: boolean;
  setActive: (active: boolean) => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
  isActive: false,
  setActive: (active) => set({ isActive: active }),
}));
