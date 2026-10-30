/** Row text and input parsing for the schedules panel.
 *
 *  Kept pure so the wording and the cron/interval parsing can be asserted without
 *  a renderer: a schedule that is displayed wrongly makes a job look like it will
 *  run when it will not.
 */
import type { NovaScheduleJob } from "../api/types.ts";

const CRON_FIELD = /^[\d*,/-]+$/;

/** Five space-separated fields of digits, ranges, steps, lists or stars. */
export function isValidCron(expr: string): boolean {
    const parts = expr.trim().split(/\s+/);
    if (parts.length !== 5) return false;
    return parts.every((part) => part.length > 0 && CRON_FIELD.test(part));
}

export type ScheduleInput =
    | { kind: "cron"; cronExpr: string }
    | { kind: "interval"; intervalMinutes: number };

/** Read the schedule step's answer: `30m` is an interval, five fields are cron. */
export function parseScheduleInput(text: string): ScheduleInput | null {
    const value = text.trim();
    if (!value) return null;
    const interval = /^(\d+)\s*m(in(ute)?s?)?$/i.exec(value);
    if (interval) {
        const minutes = Number(interval[1]);
        return minutes > 0 ? { kind: "interval", intervalMinutes: minutes } : null;
    }
    // Also accept a bare number of minutes: "30".
    if (/^\d+$/.test(value)) {
        const minutes = Number(value);
        return minutes > 0 ? { kind: "interval", intervalMinutes: minutes } : null;
    }
    return isValidCron(value) ? { kind: "cron", cronExpr: value } : null;
}

/** The schedule itself, without the run history. */
export function describeSchedule(job: NovaScheduleJob): string {
    if (job.kind === "cron") return `cron ${job.cron_expr || "?"}`;
    if (job.kind === "interval") return `every ${job.interval_minutes ?? "?"}m`;
    return `once ${job.run_at || "?"}`;
}

/** `in 3m`, `2h ago`, or `-` when the timestamp is absent. */
export function relativeTime(iso: string | null, now = Date.now()): string {
    if (!iso) return "-";
    const at = Date.parse(iso);
    if (Number.isNaN(at)) return "-";
    const seconds = Math.round((at - now) / 1000);
    const past = seconds < 0;
    const size = Math.abs(seconds);
    const value =
        size < 60
            ? `${size}s`
            : size < 3600
              ? `${Math.round(size / 60)}m`
              : size < 86400
                ? `${Math.round(size / 3600)}h`
                : `${Math.round(size / 86400)}d`;
    return past ? `${value} ago` : `in ${value}`;
}

/** Status word for the last run, with the glyph that survives a narrow terminal. */
export function lastStatusLabel(job: NovaScheduleJob): string {
    if (!job.last_status) return "never run";
    if (job.last_status === "succeeded") return "ok";
    if (job.last_status === "failed") return "failed";
    return job.last_status;
}

/** `next in 29m · last ok 47s ago`, or `paused · last never run`.

 *  A paused job keeps its old `next_run_at` on the server, so printing it would
 *  promise a run that will not happen.
 */
export function jobSummary(job: NovaScheduleJob, now = Date.now()): string {
    const state = job.enabled
        ? `next ${relativeTime(job.next_run_at, now)}`
        : "paused";
    const last = job.last_status
        ? `${lastStatusLabel(job)} ${job.last_run_at ? relativeTime(job.last_run_at, now) : ""}`.trim()
        : "never run";
    return `${state} · last ${last}`;
}

/** One list line: on/off, name, schedule, when it runs next, last result. */
export function scheduleLine(job: NovaScheduleJob, now = Date.now()): string {
    const state = job.enabled ? "●" : "○";
    const next = job.enabled ? `next ${relativeTime(job.next_run_at, now)}` : "paused";
    return `${state} ${job.name}  ·  ${describeSchedule(job)}  ·  ${next}  ·  ${lastStatusLabel(job)}`;
}
