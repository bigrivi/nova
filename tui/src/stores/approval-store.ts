/** Command approval state: one modal slot plus a FIFO for concurrent tabs.
 *
 *  The approval protocol is per request; the TUI can only show one dialog at a
 *  time. A second session's request is queued rather than dropped: a dropped
 *  request never expires server-side, so its turn would hang forever.
 */
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
    queue: ApprovalPending[];
    setPending: (pending: ApprovalPending | null) => void;
    resolve: (requestId: string) => void;
    clearRun: (runId: number) => void;
    clearSession: (sessionId: string) => void;
    dropFetched: (sessionId: string, keep: Set<string>) => void;
};

function promote(queue: ApprovalPending[]): ApprovalPending | null {
    return queue[0] ?? null;
}

export const useApprovalStore = create<ApprovalState>((set) => ({
    pending: null,
    queue: [],

    setPending: (pending) =>
        set((state) => {
            if (pending === null) {
                const queue = state.queue.slice(1);
                return { pending: state.queue[0] ?? null, queue };
            }
            if (
                state.pending?.requestId === pending.requestId ||
                state.queue.some((item) => item.requestId === pending.requestId)
            ) {
                return state;
            }
            if (state.pending === null) {
                return { pending, queue: state.queue };
            }
            return { pending: state.pending, queue: [...state.queue, pending] };
        }),

    resolve: (requestId) =>
        set((state) => {
            if (state.pending?.requestId === requestId) {
                const queue = state.queue.slice(1);
                return { pending: state.queue[0] ?? null, queue };
            }
            return {
                pending: state.pending,
                queue: state.queue.filter(
                    (item) => item.requestId !== requestId,
                ),
            };
        }),

    clearRun: (runId) =>
        set((state) => {
            if (state.pending === null && state.queue.length === 0) {
                return state;
            }
            const queue = state.queue.filter((item) => item.runId !== runId);
            if (state.pending?.runId === runId) {
                return { pending: promote(queue), queue: queue.slice(1) };
            }
            return { pending: state.pending, queue };
        }),

    clearSession: (sessionId) =>
        set((state) => {
            const queue = state.queue.filter(
                (item) => item.sessionId !== sessionId,
            );
            if (state.pending?.sessionId !== sessionId) {
                return { pending: state.pending, queue };
            }
            const next = queue[0] ?? null;
            return { pending: next, queue: next ? queue.slice(1) : queue };
        }),

    /** Drop recovered prompts that the server no longer reports.
     *
     *  Live prompts (a non-negative run id) are left to their stream; only the
     *  copies fetched from `/pending` are reconciled here.
     */
    dropFetched: (sessionId, keep) =>
        set((state) => {
            const stale = (item: ApprovalPending) =>
                item.sessionId === sessionId &&
                item.runId < 0 &&
                !keep.has(item.requestId);
            const queue = state.queue.filter((item) => !stale(item));
            if (state.pending && stale(state.pending)) {
                const next = queue[0] ?? null;
                return { pending: next, queue: next ? queue.slice(1) : queue };
            }
            return { pending: state.pending, queue };
        }),
}));
