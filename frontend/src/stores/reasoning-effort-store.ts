import { create } from "zustand";

/**
 * The reasoning level the composer sends with each turn.
 *
 * Kept in a store rather than shell state for the same reason the composer draft
 * is: the shell owns the session list and the thread, so a value held up there
 * re-renders every row and every message. Only the model selector reads this.
 *
 * The value is deliberately *not* filtered here. Which levels a model accepts
 * is data from the server, and `resolveModelEffort` applies it at render time
 * so that switching models and back does not lose the level picked for the
 * model that is coming back.
 */
type ReasoningEffortStore = {
    effort: string | null;
    setEffort: (effort: string | null) => void;
};

export const useReasoningEffortStore = create<ReasoningEffortStore>()((set) => ({
    effort: null,
    setEffort: (effort) => set({ effort }),
}));
