import { create } from "zustand";

export type ApprovalPending = {
    sessionId: string;
    requestId: string;
    command: string;
    description: string;
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
