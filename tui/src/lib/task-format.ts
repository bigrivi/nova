/** Row text for the background-task panel.
 *
 *  Kept free of React so the labels can be asserted directly: "running 3m" and
 *  "failed" are the whole signal a user gets from a list they scan in passing.
 */
import type { NovaTask } from "../api/types.ts";

/** Short status word, with the one glyph that survives a narrow terminal. */
export function taskStatusLabel(status: string): string {
    if (status === "running") return "● running";
    if (status === "queued") return "○ queued";
    if (status === "succeeded" || status === "completed") return "✓ done";
    if (status === "failed") return "✗ failed";
    if (status === "cancelled") return "⊘ cancelled";
    if (status === "timed_out") return "✗ timed out";
    return status;
}

/** Milliseconds a task has run: finished − started, or now − started. */
export function taskDurationMs(task: NovaTask, now = Date.now()): number {
    if (!task.started_at_ms) return 0;
    const end = task.finished_at_ms ?? now;
    return Math.max(0, end - task.started_at_ms);
}

/** `45s`, `3m`, `2h` — coarse on purpose; precision adds noise to a scan. */
export function formatDuration(ms: number): string {
    const seconds = Math.round(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
}

/** Whether the task can still be cancelled. */
export function isCancellable(task: NovaTask): boolean {
    return task.status === "running" || task.status === "queued";
}

/** One line: status, label, duration, and the error when it failed. */
export function taskLine(task: NovaTask, now = Date.now()): string {
    const parts = [
        taskStatusLabel(task.status),
        task.label || task.kind,
        formatDuration(taskDurationMs(task, now)),
    ];
    if (task.progress_message) parts.push(task.progress_message);
    if (task.error) parts.push(task.error);
    return parts.join(" · ");
}
