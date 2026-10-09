import { create } from "zustand";

export type ApprovalPending = {
    sessionId: string;
    requestId: string;
    command: string;
    description: string;
    /** Which tool is asking. Empty means the shell, for older replays. */
    toolName: string;
    /**
     * False when a reviewer declined this action: the prompt will recur, so the
     * dialog hides "remember" rather than offering a decision that is dropped.
     */
    rememberable: boolean;
    /**
     * What "Approve & Remember" would cover, e.g. `git push *`. Empty when there
     * is nothing to name, which is also when the button is hidden.
     */
    family: string;
    /**
     * Whether remembering would cover this inline script rather than the whole
     * family. Chosen over showing the digest: the hash is not something a user
     * can act on, and the script it stands for is the command on screen.
     */
    scriptScoped: boolean;
    /**
     * The workspace the tool path was judged against. Empty means none is
     * active, which is the case where every path is undecidable and prompts --
     * so the dialog distinguishes it from "inside, nothing to report" instead of
     * showing nothing in both cases.
     */
    workspace: string;
};

interface ApprovalStore {
    pending: ApprovalPending | null;
    pendingBySession: Record<string, ApprovalPending>;
    setPending: (pending: ApprovalPending | null) => void;
    setPendingForSession: (
        sessionId: string,
        pending: ApprovalPending | null,
    ) => void;
    clearPendingForSession: (sessionId: string) => void;
    syncPendingToSession: (sessionId: string | null) => void;
}

export const useApprovalStore = create<ApprovalStore>((set) => ({
    pending: null,
    pendingBySession: {},
    setPending: (pending) => set({ pending }),
    setPendingForSession: (sessionId, pending) =>
        set((state) => {
            const next = { ...state.pendingBySession };
            if (pending) {
                next[sessionId] = pending;
            } else {
                delete next[sessionId];
            }
            return {
                pendingBySession: next,
                pending:
                    state.pending?.sessionId === sessionId ? pending : state.pending,
            };
        }),
    clearPendingForSession: (sessionId) =>
        set((state) => {
            if (!(sessionId in state.pendingBySession)) {
                return state;
            }
            const next = { ...state.pendingBySession };
            delete next[sessionId];
            return {
                pendingBySession: next,
                pending:
                    state.pending?.sessionId === sessionId ? null : state.pending,
            };
        }),
    syncPendingToSession: (sessionId) =>
        set((state) => ({
            pending:
                sessionId == null
                    ? null
                    : (state.pendingBySession[sessionId] ?? null),
        })),
}));
