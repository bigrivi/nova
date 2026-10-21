import type {
    NovaScheduleCreateRequest,
    NovaScheduleJob,
    NovaScheduleKind,
    NovaScheduleUpdateRequest,
} from "../types/nova";

/** Form values the schedule dialog edits; strings because inputs are text. */
export type ScheduleFormValues = {
    name: string;
    prompt: string;
    kind: NovaScheduleKind;
    cronExpr: string;
    intervalMinutes: string;
    runAt: string;
    sessionId: string;
    agentKey: string;
};

export type ScheduleFormField =
    | "name"
    | "prompt"
    | "sessionId"
    | "cronExpr"
    | "intervalMinutes"
    | "runAt";

export type TranslateFn = (
    key: string,
    options?: Record<string, string | number>,
) => string;

export const CRON_PRESETS: ReadonlyArray<{
    expr: string;
    labelKey: string;
}> = [
    { expr: "*/5 * * * *", labelKey: "schedules.presetEvery5Min" },
    { expr: "0 * * * *", labelKey: "schedules.presetHourly" },
    { expr: "0 9 * * *", labelKey: "schedules.presetDaily9" },
    { expr: "0 9 * * 1", labelKey: "schedules.presetWeeklyMon9" },
];

const CRON_FIELD_PATTERN = /^[\d*,/-]+$/;

/** Five space-separated fields of digits, ranges, steps, lists or stars. */
export function isValidCron(expr: string): boolean {
    const parts = expr.trim().split(/\s+/);
    if (parts.length !== 5) {
        return false;
    }
    return parts.every(
        (part) => part.length > 0 && CRON_FIELD_PATTERN.test(part),
    );
}

export function defaultScheduleForm(
    init?: Partial<ScheduleFormValues>,
): ScheduleFormValues {
    return {
        name: "",
        prompt: "",
        kind: "cron",
        cronExpr: "0 9 * * *",
        intervalMinutes: "30",
        runAt: "",
        sessionId: "",
        agentKey: "main",
        ...init,
    };
}

export function scheduleFormFromJob(job: NovaScheduleJob): ScheduleFormValues {
    return {
        name: job.name,
        prompt: job.prompt,
        kind: job.kind,
        cronExpr: job.cron_expr || "0 9 * * *",
        intervalMinutes: String(job.interval_minutes || 30),
        runAt: toDatetimeLocalValue(job.run_at),
        sessionId: job.session_id,
        agentKey: job.agent_key || "main",
    };
}

/** Local validation; empty map means the form may be submitted. */
export function validateScheduleForm(
    values: ScheduleFormValues,
    t: TranslateFn,
): Partial<Record<ScheduleFormField, string>> {
    const errors: Partial<Record<ScheduleFormField, string>> = {};
    if (!values.name.trim()) {
        errors.name = t("schedules.errorNameRequired");
    }
    if (!values.prompt.trim()) {
        errors.prompt = t("schedules.errorPromptRequired");
    }
    if (!values.sessionId.trim()) {
        errors.sessionId = t("schedules.errorSessionRequired");
    }
    if (values.kind === "cron" && !isValidCron(values.cronExpr)) {
        errors.cronExpr = t("schedules.errorCronInvalid");
    }
    if (values.kind === "interval") {
        const minutes = Number(values.intervalMinutes);
        if (!Number.isInteger(minutes) || minutes <= 0) {
            errors.intervalMinutes = t("schedules.errorIntervalInvalid");
        }
    }
    if (values.kind === "once") {
        if (!values.runAt) {
            errors.runAt = t("schedules.errorRunAtRequired");
        } else if (Number.isNaN(new Date(values.runAt).getTime())) {
            errors.runAt = t("schedules.errorRunAtInvalid");
        }
    }
    return errors;
}

function cleanString(value: string): string {
    return value.trim();
}

/** The POST body for the active kind; only its own schedule field travels. */
export function buildCreatePayload(
    values: ScheduleFormValues,
): NovaScheduleCreateRequest {
    const payload: NovaScheduleCreateRequest = {
        name: cleanString(values.name),
        prompt: cleanString(values.prompt),
        kind: values.kind,
        session_id: cleanString(values.sessionId),
    };
    const agentKey = cleanString(values.agentKey);
    if (agentKey) {
        payload.agent_key = agentKey;
    }
    if (values.kind === "cron") {
        payload.cron_expr = values.cronExpr.trim();
    } else if (values.kind === "interval") {
        payload.interval_minutes = Number(values.intervalMinutes);
    } else {
        payload.run_at = fromDatetimeLocalValue(values.runAt);
    }
    return payload;
}

/** The PATCH body: full editor state for the active kind, like create. */
export function buildUpdatePatch(
    values: ScheduleFormValues,
): NovaScheduleUpdateRequest {
    return buildCreatePayload(values);
}

/** One-line, human-readable description of when the job runs. */
export function describeSchedule(job: NovaScheduleJob, t: TranslateFn): string {
    if (job.kind === "interval") {
        return t("schedules.describeInterval", {
            minutes: job.interval_minutes ?? 0,
        });
    }
    if (job.kind === "once") {
        return t("schedules.describeOnce", {
            time: formatDateTime(job.run_at),
        });
    }
    const preset = CRON_PRESETS.find((item) => item.expr === job.cron_expr.trim());
    if (preset) {
        return t(preset.labelKey);
    }
    return t("schedules.describeCron", { expr: job.cron_expr || "–" });
}

export function formatDateTime(iso: string | null): string {
    if (!iso) {
        return "–";
    }
    const time = new Date(iso).getTime();
    if (Number.isNaN(time)) {
        return iso;
    }
    return new Date(iso).toLocaleString();
}

/** "2026-10-21T09:00:00+08:00" -> "2026-10-21T09:00" for datetime-local. */
export function toDatetimeLocalValue(iso: string): string {
    if (!iso) {
        return "";
    }
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
        return "";
    }
    const pad = (n: number) => String(n).padStart(2, "0");
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
        `T${pad(date.getHours())}:${pad(date.getMinutes())}`
    );
}

/** "2026-10-21T09:00" -> full ISO string with the local offset attached. */
export function fromDatetimeLocalValue(local: string): string {
    if (!local) {
        return "";
    }
    const date = new Date(local);
    if (Number.isNaN(date.getTime())) {
        return local;
    }
    return date.toISOString();
}
