import { describe, expect, it } from "vitest";

import type { NovaScheduleJob } from "../types/nova";
import {
    buildCreatePayload,
    defaultScheduleForm,
    describeSchedule,
    fromDatetimeLocalValue,
    isValidCron,
    scheduleFormFromJob,
    toDatetimeLocalValue,
    validateScheduleForm,
    type TranslateFn,
} from "./schedule";

const t: TranslateFn = (key, options) => {
    if (!options) {
        return key;
    }
    return `${key}:${Object.values(options).join(",")}`;
};

function job(overrides: Partial<NovaScheduleJob> = {}): NovaScheduleJob {
    return {
        id: "job-1",
        name: "Morning brief",
        prompt: "Summarize overnight activity",
        kind: "cron",
        cron_expr: "0 9 * * *",
        interval_minutes: 30,
        run_at: "",
        enabled: true,
        session_id: "s1",
        agent_key: "main",
        next_run_at: "2026-10-22T09:00:00+08:00",
        last_run_at: null,
        last_status: "",
        last_error: "",
        created_at: 1761000000,
        ...overrides,
    };
}

describe("isValidCron", () => {
    it("accepts the documented presets", () => {
        for (const expr of ["*/5 * * * *", "0 * * * *", "0 9 * * *", "0 9 * * 1"]) {
            expect(isValidCron(expr)).toBe(true);
        }
    });

    it("rejects wrong field counts and junk", () => {
        expect(isValidCron("0 9 * *")).toBe(false);
        expect(isValidCron("0 9 * * * *")).toBe(false);
        expect(isValidCron("")).toBe(false);
        expect(isValidCron("every day at 9")).toBe(false);
        expect(isValidCron("0 9 * * MON")).toBe(false);
    });
});

describe("validateScheduleForm", () => {
    it("passes a complete cron form", () => {
        const errors = validateScheduleForm(
            defaultScheduleForm({
                name: "Brief",
                prompt: "Summarize",
                sessionId: "s1",
                kind: "cron",
                cronExpr: "0 9 * * *",
            }),
            t,
        );
        expect(errors).toEqual({});
    });

    it("requires name, prompt and session", () => {
        const errors = validateScheduleForm(defaultScheduleForm(), t);
        expect(errors.name).toBeDefined();
        expect(errors.prompt).toBeDefined();
        expect(errors.sessionId).toBeDefined();
    });

    it("rejects bad cron expressions", () => {
        const errors = validateScheduleForm(
            defaultScheduleForm({
                name: "x",
                prompt: "y",
                sessionId: "s1",
                cronExpr: "not a cron",
            }),
            t,
        );
        expect(errors.cronExpr).toBeDefined();
    });

    it("rejects non-positive intervals", () => {
        for (const intervalMinutes of ["0", "-5", "1.5", "abc"]) {
            const errors = validateScheduleForm(
                defaultScheduleForm({
                    name: "x",
                    prompt: "y",
                    sessionId: "s1",
                    kind: "interval",
                    intervalMinutes,
                }),
                t,
            );
            expect(errors.intervalMinutes).toBeDefined();
        }
    });

    it("requires run_at for one-shot jobs", () => {
        const errors = validateScheduleForm(
            defaultScheduleForm({
                name: "x",
                prompt: "y",
                sessionId: "s1",
                kind: "once",
                runAt: "",
            }),
            t,
        );
        expect(errors.runAt).toBeDefined();
    });
});

describe("buildCreatePayload", () => {
    it("sends only the cron field for cron jobs", () => {
        const payload = buildCreatePayload(
            defaultScheduleForm({
                name: " Brief ",
                prompt: "Go",
                sessionId: "s1",
                kind: "cron",
                cronExpr: "0 9 * * *",
            }),
        );
        expect(payload).toEqual({
            name: "Brief",
            prompt: "Go",
            kind: "cron",
            session_id: "s1",
            agent_key: "main",
            cron_expr: "0 9 * * *",
        });
    });

    it("sends minutes as a number for interval jobs", () => {
        const payload = buildCreatePayload(
            defaultScheduleForm({
                name: "x",
                prompt: "y",
                sessionId: "s1",
                kind: "interval",
                intervalMinutes: "15",
            }),
        );
        expect(payload.interval_minutes).toBe(15);
        expect(payload).not.toHaveProperty("cron_expr");
        expect(payload).not.toHaveProperty("run_at");
    });
});

describe("describeSchedule", () => {
    it("names cron presets instead of echoing the expression", () => {
        expect(describeSchedule(job(), t)).toBe("schedules.presetDaily9");
    });

    it("echoes custom cron expressions", () => {
        expect(
            describeSchedule(job({ cron_expr: "30 8 * * *" }), t),
        ).toContain("30 8 * * *");
    });

    it("mentions minutes for interval jobs", () => {
        expect(
            describeSchedule(job({ kind: "interval", interval_minutes: 15 }), t),
        ).toContain("15");
    });
});

describe("datetime-local round trip", () => {
    it("formats ISO for the input and parses it back", () => {
        const local = toDatetimeLocalValue("2026-10-21T09:00:00+08:00");
        expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
        expect(new Date(fromDatetimeLocalValue(local)).getTime()).not.toBeNaN();
    });

    it("round-trips a job's run_at through the form", () => {
        const values = scheduleFormFromJob(
            job({ kind: "once", run_at: "2026-10-21T09:00:00+08:00" }),
        );
        expect(values.runAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    });

    it("tolerates blanks and garbage", () => {
        expect(toDatetimeLocalValue("")).toBe("");
        expect(toDatetimeLocalValue("junk")).toBe("");
        expect(fromDatetimeLocalValue("")).toBe("");
    });
});
