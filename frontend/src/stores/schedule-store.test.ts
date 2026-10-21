import { beforeEach, describe, expect, it } from "vitest";

import type { NovaScheduleJob } from "../types/nova";
import { useScheduleStore } from "./schedule-store";

function job(overrides: Partial<NovaScheduleJob> = {}): NovaScheduleJob {
    return {
        id: "job-1",
        name: "Morning brief",
        prompt: "Summarize",
        kind: "cron",
        cron_expr: "0 9 * * *",
        interval_minutes: 30,
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

beforeEach(() => {
    useScheduleStore.getState().reset();
});

describe("schedule store", () => {
    it("replaces the list on refresh", () => {
        const store = useScheduleStore.getState();
        store.upsertSchedule(job({ id: "stale" }));
        store.setSchedules([job({ id: "fresh" })]);

        expect(useScheduleStore.getState().schedules.map((i) => i.id)).toEqual([
            "fresh",
        ]);
    });

    it("upserts without duplicating rows", () => {
        const store = useScheduleStore.getState();
        store.upsertSchedule(job({ name: "v1" }));
        store.upsertSchedule(job({ name: "v2" }));

        const schedules = useScheduleStore.getState().schedules;
        expect(schedules).toHaveLength(1);
        expect(schedules[0].name).toBe("v2");
    });

    it("removes a deleted schedule", () => {
        const store = useScheduleStore.getState();
        store.setSchedules([job({ id: "a" }), job({ id: "b" })]);
        store.removeSchedule("a");

        expect(useScheduleStore.getState().schedules.map((i) => i.id)).toEqual([
            "b",
        ]);
    });
});
