/** Unsent composer text, one draft per tab. */
import { create } from "zustand";

type DraftsState = {
    byTab: Record<string, string>;
    setText: (tabId: string, text: string) => void;
    clear: (tabId: string) => void;
    reset: () => void;
};

export const useDrafts = create<DraftsState>((set) => ({
    byTab: {},
    setText: (tabId, text) =>
        set((state) => ({
            byTab: { ...state.byTab, [tabId]: text },
        })),
    clear: (tabId) =>
        set((state) => {
            if (!(tabId in state.byTab)) {
                return state;
            }
            const byTab = { ...state.byTab };
            delete byTab[tabId];
            return { byTab };
        }),
    reset: () => set({ byTab: {} }),
}));
