import { create } from "zustand";

/**
 * Composer draft text lives outside the React tree on purpose: the shell owns
 * the session list and the thread viewport, so draft state held up there
 * re-rendered every session row and every message on each keystroke. Only the
 * textarea subscribes.
 */
type ComposerStore = {
    text: string;
    setText: (text: string) => void;
    clear: () => void;
};

export const useComposerStore = create<ComposerStore>()((set) => ({
    text: "",
    setText: (text) => set({ text }),
    clear: () => set({ text: "" }),
}));
