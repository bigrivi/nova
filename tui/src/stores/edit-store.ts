/** The question being edited, and where it came from.
 *
 * Editing a question is a mode, not a message: the text sits in the composer
 * until it is sent, and the message it replaces stays in the transcript until
 * then. A store, because the picker that chooses the question and the
 * composer that holds the new text are different components.
 */

import { create } from "zustand";

export type EditState = {
    /** The message being replaced, or null when nothing is being edited. */
    messageId: string | null;
    /** The text as it was, so the composer can show what is being replaced. */
    originalText: string;
    set: (messageId: string, originalText: string) => void;
    clear: () => void;
};

export const useEditStore = create<EditState>((set) => ({
    messageId: null,
    originalText: "",
    set: (messageId, originalText) => set({ messageId, originalText }),
    clear: () => set({ messageId: null, originalText: "" }),
}));
