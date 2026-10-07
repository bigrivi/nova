import type { ToolCallMessagePartStatus } from "@assistant-ui/react";

import type { NovaBackgroundTaskStatus } from "@/types/nova";

export type ToolOutcome = {
    isRunning: boolean;
    isCancelled: boolean;
    errored: boolean;
};

/**
 * Fold a tool part's status, error flag and detached background task state
 * into the three states every tool surface has to agree on.
 *
 * A detached background task keeps living after the tool call returned its
 * handle (so the part itself reads "complete"), which is why the task's own
 * state overrides the part status instead of merely adding to it.
 *
 * @param status - The tool call part's own status, absent for unknown tools.
 * @param isError - Whether the tool result itself was flagged as an error.
 * @param backgroundState - Live status of the detached task, when there is one.
 * @returns The resolved running, cancelled and errored flags.
 */
export function readToolOutcome(
    status: ToolCallMessagePartStatus | undefined,
    isError: boolean | undefined,
    backgroundState: NovaBackgroundTaskStatus | null,
): ToolOutcome {
    const taskRunning =
        backgroundState === "queued" || backgroundState === "running";
    const taskFailed =
        backgroundState === "failed" || backgroundState === "timed_out";
    const isCancelled =
        (status?.type === "incomplete" && status.reason === "cancelled") ||
        backgroundState === "cancelled";
    const statusError =
        status?.type === "incomplete" && !isCancelled && status.error != null;

    return {
        isRunning: status?.type === "running" || taskRunning,
        isCancelled,
        errored:
            (isError === true || statusError || taskFailed) && !taskRunning,
    };
}