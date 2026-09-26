import { beforeEach, describe, expect, it } from "vitest";

import type { NovaBackgroundTask } from "../types/nova";
import { useBackgroundTaskStore } from "./background-task-store";

function task(overrides: Partial<NovaBackgroundTask>): NovaBackgroundTask {
    return {
        task_id: "t1",
        kind: "shell",
        session_id: "s1",
        label: "Example",
        status: "running",
        background: true,
        created_at_ms: 1000,
        started_at_ms: 1000,
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
    useBackgroundTaskStore.setState({
        activeSessionId: null,
        tasksBySession: {},
        tasksById: {},
        error: null,
    });
});

describe("replaceTasks", () => {
    it("groups background tasks per session, newest first", () => {
        useBackgroundTaskStore.getState().replaceTasks([
            task({ task_id: "old", created_at_ms: 1000 }),
            task({ task_id: "new", created_at_ms: 5000 }),
        ]);

        const state = useBackgroundTaskStore.getState();
        expect(state.tasksBySession.s1.map((item) => item.task_id)).toEqual([
            "new",
            "old",
        ]);
        expect(Object.keys(state.tasksById).sort()).toEqual(["new", "old"]);
    });

    it("keeps foreground tasks out of the panel list but in tasksById", () => {
        useBackgroundTaskStore
            .getState()
            .replaceTasks([task({ task_id: "fg", background: false })]);

        const state = useBackgroundTaskStore.getState();
        expect(state.tasksBySession).toEqual({});
        expect(state.tasksById.fg).toBeDefined();
    });

    it("drops tasks the server no longer retains", () => {
        const store = useBackgroundTaskStore.getState();
        store.replaceTasks([task({ task_id: "gone" })]);
        store.replaceTasks([]);

        expect(useBackgroundTaskStore.getState().tasksById).toEqual({});
        expect(useBackgroundTaskStore.getState().tasksBySession).toEqual({});
    });
});

describe("updateTask", () => {
    it("upserts a status change without duplicating the row", () => {
        const store = useBackgroundTaskStore.getState();
        store.updateTask(task({ task_id: "t1", status: "running" }));
        store.updateTask(task({ task_id: "t1", status: "succeeded" }));

        const list = useBackgroundTaskStore.getState().tasksBySession.s1;
        expect(list).toHaveLength(1);
        expect(list[0].status).toBe("succeeded");
        expect(useBackgroundTaskStore.getState().tasksById.t1.status).toBe(
            "succeeded",
        );
    });

    it("adds a task detached later into the panel list", () => {
        const store = useBackgroundTaskStore.getState();
        store.updateTask(task({ task_id: "t1", background: false }));
        expect(useBackgroundTaskStore.getState().tasksBySession).toEqual({});

        store.updateTask(task({ task_id: "t1", background: true }));
        expect(
            useBackgroundTaskStore.getState().tasksBySession.s1.map((i) => i.task_id),
        ).toEqual(["t1"]);
    });
});
