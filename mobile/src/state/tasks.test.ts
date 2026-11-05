import { beforeEach, describe, expect, test } from "bun:test";

import type { NovaBackgroundTask } from "../api/types";
import { useTasks } from "./tasks";

function task(
    id: string,
    overrides: Partial<NovaBackgroundTask> = {},
): NovaBackgroundTask {
    return {
        task_id: id,
        kind: "bash",
        session_id: "ses_1",
        label: id,
        status: "running",
        background: true,
        created_at_ms: 1,
        started_at_ms: null,
        finished_at_ms: null,
        timeout_seconds: 60,
        exit_code: null,
        output_bytes: 0,
        output_truncated: false,
        result: "",
        error: null,
        progress: null,
        progress_message: null,
        last_activity_at_ms: null,
        ...overrides,
    };
}

beforeEach(() => {
    useTasks.getState().reset();
});

describe("background task store", () => {
    test("snapshot groups background tasks by session, newest first", () => {
        useTasks.getState().replace([
            task("old", { created_at_ms: 1 }),
            task("new", { created_at_ms: 2 }),
            task("sync", { background: false }),
        ]);

        const state = useTasks.getState();
        expect(state.bySession.ses_1!.map((item) => item.task_id)).toEqual([
            "new",
            "old",
        ]);
        expect(state.byId.sync).toBeDefined();
    });

    test("updates replace in place and add unknown tasks", () => {
        useTasks.getState().replace([task("a", { created_at_ms: 1 })]);
        useTasks
            .getState()
            .update(task("a", { created_at_ms: 1, status: "succeeded" }));
        useTasks.getState().update(task("b", { created_at_ms: 2 }));

        const state = useTasks.getState();
        expect(state.bySession.ses_1![0]!.task_id).toBe("b");
        expect(state.bySession.ses_1![1]!.status).toBe("succeeded");
    });

    test("reset clears both indexes", () => {
        useTasks.getState().replace([task("a")]);
        useTasks.getState().reset();

        expect(useTasks.getState().byId).toEqual({});
        expect(useTasks.getState().bySession).toEqual({});
    });
});
