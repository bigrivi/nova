/** Command approval state: shell commands pending approval (zustand) */
import { create } from "zustand";

export type ApprovalPending = {
    sessionId: string;
    requestId: string;
    command: string;
    description: string;
};

type ApprovalState = {
    pending: ApprovalPending | null;
    setPending: (pending: ApprovalPending | null) => void;
};

export const useApprovalStore = create<ApprovalState>((set) => ({
    pending: null,
    setPending: (pending) => set({ pending }),
}));
