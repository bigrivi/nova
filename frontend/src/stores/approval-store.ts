import { create } from "zustand";

export type ApprovalPending = {
  sessionId: string;
  requestId: string;
  command: string;
  description: string;
};

interface ApprovalStore {
  pending: ApprovalPending | null;
  setPending: (pending: ApprovalPending | null) => void;
}

export const useApprovalStore = create<ApprovalStore>((set) => ({
  pending: null,
  setPending: (pending) => set({ pending }),
}));
