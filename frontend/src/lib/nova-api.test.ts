// The five schedule endpoints: URL, method, body and response shape each.
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NovaScheduleJob } from "../types/nova";
import {
    createSchedule,
    deleteSchedule,
    listSchedules,
    runScheduleNow,
    updateSchedule,
} from "./nova-api";

function job(overrides: Partial<NovaScheduleJob> = {}): NovaScheduleJob {
    return {
        id: "job-1",
        name: "Morning brief",
        prompt: "Summarize",
        kind: "cron",
        cron_expr: "0 9 * * *",
        interval_minutes: null,
        run_at: "",
        enabled: true,
        session_id: "s1",
        agent_key: "main",
        next_run_at: null,
        last_run_at: null,
        last_status: "",
        last_error: "",
        created_at: 1761000000,
        ...overrides,
    };
}

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

function stubFetch(response: Response) {
    const fetchMock = vi.fn(
        async (_url: string, _init?: RequestInit) => response,
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("schedule api", () => {
    it("lists schedules with a GET", async () => {
        const fetchMock = stubFetch(jsonResponse({ schedules: [job()] }));

        await expect(listSchedules()).resolves.toEqual([job()]);

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/schedules");
        expect(init).not.toHaveProperty("method");
    });

    it("creates a schedule with a POST body", async () => {
        const payload = {
            name: "Morning brief",
            prompt: "Summarize",
            kind: "cron" as const,
            session_id: "s1",
            cron_expr: "0 9 * * *",
        };
        const fetchMock = stubFetch(jsonResponse({ schedule: job() }));

        await expect(createSchedule(payload)).resolves.toEqual(job());

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/schedules");
        expect(init).toMatchObject({ method: "POST" });
        expect(JSON.parse(String(init?.body))).toEqual(payload);
    });

    it("updates a schedule with a PATCH to the encoded id", async () => {
        const updated = job({ enabled: false });
        const fetchMock = stubFetch(jsonResponse({ schedule: updated }));

        await expect(
            updateSchedule("job/1", { enabled: false }),
        ).resolves.toEqual(updated);

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/schedules/job%2F1");
        expect(init).toMatchObject({ method: "PATCH" });
        expect(JSON.parse(String(init?.body))).toEqual({
            enabled: false,
        });
    });

    it("deletes a schedule with a DELETE", async () => {
        const fetchMock = stubFetch(new Response(null, { status: 204 }));

        await expect(deleteSchedule("job-1")).resolves.toBeUndefined();

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/schedules/job-1");
        expect(init).toMatchObject({ method: "DELETE" });
    });

    it("triggers a run with a POST and returns the task id", async () => {
        const fetchMock = stubFetch(
            jsonResponse({ ok: true, task_id: "task-1" }),
        );

        await expect(runScheduleNow("job-1")).resolves.toBe("task-1");

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/schedules/job-1/run");
        expect(init).toMatchObject({ method: "POST" });
    });
});
