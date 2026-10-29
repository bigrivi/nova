import { describe, expect, test } from "bun:test";
import type { NovaTask } from "../api/types.ts";
import {
    formatDuration,
    isCancellable,
    taskDurationMs,
    taskLine,
    taskStatusLabel,
} from "./task-format.ts";

function task(overrides: Partial<NovaTask> = {}): NovaTask {
    return {
        task_id: "t1",
        kind: "shell",
        session_id: "s1",
        label: "npm test",
        status: "running",
        background: true,
        created_at_ms: 1_000,
        started_at_ms: 1_000,
        finished_at_ms: null,
        timeout_seconds: 120,
        exit_code: null,
        output_bytes: 0,
        output_truncated: false,
        result: "",
        error: null,
        progress: null,
        progress_message: null,
        last_activity_at_ms: null,
        metadata: {},
        ...overrides,
    };
}

describe("taskStatusLabel", () => {
    test("names the states the backend emits", () => {
        expect(taskStatusLabel("running")).toContain("running");
        expect(taskStatusLabel("succeeded")).toContain("done");
        expect(taskStatusLabel("completed")).toContain("done");
        expect(taskStatusLabel("failed")).toContain("failed");
        expect(taskStatusLabel("timed_out")).toContain("timed out");
        expect(taskStatusLabel("cancelled")).toContain("cancelled");
    });

    test("passes an unknown status through", () => {
        expect(taskStatusLabel("weird")).toBe("weird");
    });
});

describe("taskDurationMs", () => {
    test("measures a finished task", () => {
        expect(
            taskDurationMs(task({ finished_at_ms: 61_000 }), 999_999),
        ).toBe(60_000);
    });

    test("runs to now while unfinished", () => {
        expect(taskDurationMs(task(), 11_000)).toBe(10_000);
    });

    test("is zero before it starts", () => {
        expect(taskDurationMs(task({ started_at_ms: null }), 5_000)).toBe(0);
    });
});

describe("formatDuration", () => {
    test("rounds to the unit that matters", () => {
        expect(formatDuration(45_000)).toBe("45s");
        expect(formatDuration(180_000)).toBe("3m");
        expect(formatDuration(7_200_000)).toBe("2h");
    });
});

describe("isCancellable", () => {
    test("only while queued or running", () => {
        expect(isCancellable(task({ status: "running" }))).toBe(true);
        expect(isCancellable(task({ status: "queued" }))).toBe(true);
        expect(isCancellable(task({ status: "succeeded" }))).toBe(false);
    });
});

describe("taskLine", () => {
    test("shows status, label and duration", () => {
        const line = taskLine(task(), 61_000);
        expect(line).toContain("running");
        expect(line).toContain("npm test");
        expect(line).toContain("1m");
    });

    test("appends progress and the error when present", () => {
        const line = taskLine(
            task({
                status: "failed",
                progress_message: "3/10 tests",
                error: "boom",
            }),
            2_000,
        );
        expect(line).toContain("3/10 tests");
        expect(line).toContain("boom");
        expect(line).toContain("failed");
    });
});
