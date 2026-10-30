import { afterEach, describe, expect, test } from "bun:test";
import {
    createSchedule,
    deleteSchedule,
    listSchedules,
    runScheduleNow,
    setScheduleEnabled,
} from "./schedules.ts";

type Call = { url: string; init?: RequestInit };

const originalFetch = globalThis.fetch;
let calls: Call[] = [];

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

function mockFetch(handler: (call: Call) => Response): void {
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
        const call = { url: String(input), init };
        calls.push(call);
        return Promise.resolve(handler(call));
    }) as typeof fetch;
}

afterEach(() => {
    globalThis.fetch = originalFetch;
    calls = [];
});

describe("schedules api", () => {
    test("listSchedules unwraps its own key, not `items`", async () => {
        mockFetch(() => jsonResponse({ schedules: [{ id: "j1" }] }));

        expect(await listSchedules()).toEqual([{ id: "j1" }] as never);
        expect(calls[0]?.url).toEndWith("/api/schedules");
    });

    test("createSchedule sends a cron expression", async () => {
        mockFetch(() => jsonResponse({ schedule: { id: "j1" } }));

        await createSchedule({
            name: "daily",
            prompt: "summarise",
            sessionId: "s1",
            agentKey: "main",
            kind: "cron",
            cronExpr: "0 9 * * *",
        });

        expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({
            name: "daily",
            prompt: "summarise",
            session_id: "s1",
            agent_key: "main",
            kind: "cron",
            cron_expr: "0 9 * * *",
        });
    });

    test("createSchedule sends minutes for an interval", async () => {
        mockFetch(() => jsonResponse({ schedule: { id: "j1" } }));

        await createSchedule({
            name: "watch",
            prompt: "check ci",
            sessionId: "s1",
            agentKey: "main",
            kind: "interval",
            intervalMinutes: 30,
        });

        const body = JSON.parse(String(calls[0]?.init?.body));
        expect(body.kind).toBe("interval");
        expect(body.interval_minutes).toBe(30);
        expect(body.cron_expr).toBeUndefined();
    });

    test("setScheduleEnabled patches only the flag", async () => {
        mockFetch(() => jsonResponse({ schedule: { id: "j1", enabled: false } }));

        const job = await setScheduleEnabled("j1", false);

        expect(job.enabled).toBe(false);
        expect(calls[0]?.url).toEndWith("/api/schedules/j1");
        expect(calls[0]?.init?.method).toBe("PATCH");
        expect(JSON.parse(String(calls[0]?.init?.body))).toEqual({ enabled: false });
    });

    test("runScheduleNow posts to the run route", async () => {
        mockFetch(() => jsonResponse({ ok: true, task_id: "t1" }));

        await runScheduleNow("j1");

        expect(calls[0]?.url).toEndWith("/api/schedules/j1/run");
        expect(calls[0]?.init?.method).toBe("POST");
    });

    test("deleteSchedule surfaces a 404 as an error", async () => {
        mockFetch(() => jsonResponse({ detail: "Schedule not found" }, 404));

        await expect(deleteSchedule("nope")).rejects.toThrow("Schedule not found");
        expect(calls[0]?.init?.method).toBe("DELETE");
    });
});
