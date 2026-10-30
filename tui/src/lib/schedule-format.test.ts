import { describe, expect, test } from "bun:test";
import type { NovaScheduleJob } from "../api/types.ts";
import {
    describeSchedule,
    isValidCron,
    jobSummary,
    lastStatusLabel,
    parseScheduleInput,
    relativeTime,
    scheduleLine,
} from "./schedule-format.ts";

function job(overrides: Partial<NovaScheduleJob> = {}): NovaScheduleJob {
    const now = Date.now();
    return {
        id: "s1",
        name: "daily-report",
        prompt: "summarise the repo",
        kind: "cron",
        cron_expr: "0 9 * * *",
        interval_minutes: null,
        run_at: "",
        enabled: true,
        session_id: "sess",
        agent_key: "main",
        next_run_at: new Date(now + 3 * 60_000).toISOString(),
        last_run_at: new Date(now - 120_000).toISOString(),
        last_status: "succeeded",
        last_error: "",
        created_at: now,
        ...overrides,
    };
}

describe("isValidCron", () => {
    test("accepts five fields of digits, ranges, steps and stars", () => {
        expect(isValidCron("0 9 * * *")).toBe(true);
        expect(isValidCron("*/5 * * * *")).toBe(true);
        expect(isValidCron("0 9 * * 1-5")).toBe(true);
        expect(isValidCron("0,30 8-18/2 * * *")).toBe(true);
    });

    test("rejects the wrong number of fields or unknown characters", () => {
        expect(isValidCron("0 9 * *")).toBe(false);
        expect(isValidCron("0 9 * * * *")).toBe(false);
        expect(isValidCron("every day")).toBe(false);
        expect(isValidCron("0 9 * * MON")).toBe(false);
    });
});

describe("parseScheduleInput", () => {
    test("reads an interval in minutes", () => {
        expect(parseScheduleInput("30m")).toEqual({
            kind: "interval",
            intervalMinutes: 30,
        });
        expect(parseScheduleInput("45 minutes")).toEqual({
            kind: "interval",
            intervalMinutes: 45,
        });
        expect(parseScheduleInput("15")).toEqual({
            kind: "interval",
            intervalMinutes: 15,
        });
    });

    test("reads a cron expression", () => {
        expect(parseScheduleInput("0 9 * * *")).toEqual({
            kind: "cron",
            cronExpr: "0 9 * * *",
        });
    });

    test("refuses nonsense and zero intervals", () => {
        expect(parseScheduleInput("")).toBeNull();
        expect(parseScheduleInput("every now and then")).toBeNull();
        expect(parseScheduleInput("0m")).toBeNull();
    });
});

describe("describeSchedule", () => {
    test("names each kind", () => {
        expect(describeSchedule(job())).toBe("cron 0 9 * * *");
        expect(
            describeSchedule(job({ kind: "interval", interval_minutes: 30 })),
        ).toBe("every 30m");
        expect(describeSchedule(job({ kind: "once", run_at: "2026-11-01T09:00" }))).toBe(
            "once 2026-11-01T09:00",
        );
    });
});

describe("relativeTime", () => {
    test("counts forward and backward", () => {
        const now = Date.parse("2026-10-30T12:00:00Z");
        expect(relativeTime("2026-10-30T12:03:00Z", now)).toBe("in 3m");
        expect(relativeTime("2026-10-30T11:58:00Z", now)).toBe("2m ago");
        expect(relativeTime("2026-11-02T12:00:00Z", now)).toBe("in 3d");
    });

    test("missing or unreadable timestamps are a dash", () => {
        expect(relativeTime(null)).toBe("-");
        expect(relativeTime("not a date")).toBe("-");
    });
});

describe("lastStatusLabel", () => {
    test("translates the backend's vocabulary", () => {
        expect(lastStatusLabel(job({ last_status: "succeeded" }))).toBe("ok");
        expect(lastStatusLabel(job({ last_status: "failed" }))).toBe("failed");
        expect(lastStatusLabel(job({ last_status: "missed" }))).toBe("missed");
        expect(lastStatusLabel(job({ last_status: "" }))).toBe("never run");
    });
});

describe("scheduleLine", () => {
    test("shows state, name, schedule, next run and last result", () => {
        const line = scheduleLine(job());
        expect(line).toContain("●");
        expect(line).toContain("daily-report");
        expect(line).toContain("cron 0 9 * * *");
        expect(line).toContain("next in 3m");
        expect(line).toContain("ok");
    });

    test("a paused job says so instead of showing a next run", () => {
        const line = scheduleLine(job({ enabled: false }));
        expect(line).toContain("○");
        expect(line).toContain("paused");
    });
});

describe("jobSummary", () => {
    test("an enabled job says when it runs next", () => {
        expect(jobSummary(job())).toContain("next in 3m");
        expect(jobSummary(job())).toContain("last ok");
    });

    test("a paused job promises nothing", () => {
        const summary = jobSummary(job({ enabled: false }));
        expect(summary.startsWith("paused")).toBe(true);
        expect(summary).not.toContain("next");
    });

    test("a job that never ran says so", () => {
        expect(
            jobSummary(job({ last_status: "", last_run_at: null })),
        ).toContain("last never run");
    });
});
