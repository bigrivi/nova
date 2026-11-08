/** The single tool-row state rule shared by every card. */
import type { ToolPart } from "../state/chat";

export type ToolState =
    | "waiting"
    | "running"
    | "done"
    | "error"
    | "cancelled";

/**
 * Fold the tool call's own status and its live background task into one state.
 *
 * A detached task outlives the call that returned its handle, so its state
 * wins over the call's "done". An approval pending on this call wins over
 * everything: the tool has not started work yet.
 *
 * @param input Tool status, optional background task status, pending approval.
 * @returns The state the row renders.
 */
export function readToolState({
    status,
    taskStatus,
    waiting = false,
}: {
    status: ToolPart["status"];
    taskStatus?: string | null;
    waiting?: boolean;
}): ToolState {
    if (waiting) {
        return "waiting";
    }
    if (taskStatus === "failed" || taskStatus === "timed_out") {
        return "error";
    }
    if (taskStatus === "cancelled" || taskStatus === "interrupted") {
        return "cancelled";
    }
    if (taskStatus === "queued" || taskStatus === "running") {
        return "running";
    }
    if (status === "error") {
        return "error";
    }
    if (status === "running") {
        return "running";
    }
    return "done";
}

/** Human-readable state, used in the header and the accessibility label. */
export function toolStateLabel(state: ToolState): string {
    if (state === "waiting") {
        return "waiting for approval";
    }
    return state;
}
