/** Command approval state: shell commands pending approval (zustand) */
import { create } from "zustand";

export type ApprovalPending = {
    sessionId: string;
    requestId: string;
    command: string;
    description: string;
    /** Which tool is asking. Empty means the shell, for older replays. */
    toolName: string;
    /** False when a reviewer declined: remembering would store nothing. */
    rememberable: boolean;
    /** What "Approve & Remember" covers, e.g. `git push *`. */
    family: string;
    /** The exact file path the tool is about to touch. */
    target: string;
    /** Whether remembering covers this inline script rather than the family. */
    scriptScoped: boolean;
    /** True only when the shell danger layer flagged this command. */
    dangerous: boolean;
    /** The workspace the path was judged against; empty when none is active. */
    workspace: string;
    runId: number;
};

type ApprovalState = {
    pending: ApprovalPending | null;
    setPending: (pending: ApprovalPending | null) => void;
};

export const useApprovalStore = create<ApprovalState>((set) => ({
    pending: null,
    setPending: (pending) => set({ pending }),
}));
