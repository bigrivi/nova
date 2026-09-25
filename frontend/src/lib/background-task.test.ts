import { describe, expect, it } from "vitest";

import {
    readBackgroundTaskEnvelope,
    readBackgroundTaskReference,
} from "./background-task";

describe("background task result parsing", () => {
    it("recognizes an explicit background tool argument before it returns", () => {
        expect(
            readBackgroundTaskReference(
                JSON.stringify({ run_in_background: true }),
                undefined,
            ),
        ).toEqual({ taskId: null, status: null, message: null });
    });

    it("reads a structured task handle from a tool result", () => {
        const result = {
            background_task: { task_id: "task-1", status: "running" },
            message: "Started",
        };

        expect(readBackgroundTaskReference(undefined, result)).toEqual({
            taskId: "task-1",
            status: "running",
            message: "Started",
        });
        expect(readBackgroundTaskEnvelope(JSON.stringify(result))).toEqual({
            taskId: "task-1",
            status: "running",
            message: "Started",
        });
    });

    it("does not mark an ordinary foreground tool result", () => {
        expect(
            readBackgroundTaskReference(
                JSON.stringify({ run_in_background: false }),
                { content: "done" },
            ),
        ).toBeNull();
    });

    it("does not mark a background request that failed to start", () => {
        expect(
            readBackgroundTaskReference(
                JSON.stringify({ run_in_background: true }),
                { content: "capacity full" },
            ),
        ).toBeNull();
    });
});
