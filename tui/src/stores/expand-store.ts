import { create } from "zustand";

export const useExpandStore = create<{ expanded: boolean; toggle: () => void }>((set) => ({
    expanded: false,
    toggle: () => set((state) => ({ expanded: !state.expanded })),
}));