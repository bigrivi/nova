/** Scheduled jobs: list, toggle, run now, delete and create.
 *
 *  The wire contract is `{"schedules": [...]}` rather than the `{"items": [...]}`
 *  every other list route uses, so it gets its own unwrapping here instead of
 *  pretending to be one of them.
 */
import { jsonInit, request } from "./client.ts";
import type { NovaScheduleJob } from "./types.ts";

export type ScheduleDraft = {
    name: string;
    prompt: string;
    sessionId: string;
    agentKey: string;
    kind: "cron" | "interval";
    cronExpr?: string;
    intervalMinutes?: number;
};

export async function listSchedules(): Promise<NovaScheduleJob[]> {
    const payload = await request<{ schedules: NovaScheduleJob[] }>(
        "/api/schedules",
    );
    return payload.schedules;
}

export async function createSchedule(
    draft: ScheduleDraft,
): Promise<NovaScheduleJob> {
    const body: Record<string, unknown> = {
        name: draft.name,
        prompt: draft.prompt,
        session_id: draft.sessionId,
        agent_key: draft.agentKey,
        kind: draft.kind,
    };
    if (draft.kind === "cron") {
        body.cron_expr = draft.cronExpr ?? "";
    } else {
        body.interval_minutes = draft.intervalMinutes ?? 0;
    }
    const payload = await request<{ schedule: NovaScheduleJob }>(
        "/api/schedules",
        jsonInit("POST", body),
    );
    return payload.schedule;
}

/** Enable or disable a job. Disabling leaves the schedule but stops firing. */
export async function setScheduleEnabled(
    jobId: string,
    enabled: boolean,
): Promise<NovaScheduleJob> {
    const payload = await request<{ schedule: NovaScheduleJob }>(
        `/api/schedules/${jobId}`,
        jsonInit("PATCH", { enabled }),
    );
    return payload.schedule;
}

/** Fire once, now, through the same background-task channel a tick uses. */
export async function runScheduleNow(jobId: string): Promise<void> {
    await request<{ task?: unknown }>(
        `/api/schedules/${jobId}/run`,
        { method: "POST" },
    );
}

export async function deleteSchedule(jobId: string): Promise<void> {
    await request<{ ok: boolean }>(`/api/schedules/${jobId}`, {
        method: "DELETE",
    });
}
