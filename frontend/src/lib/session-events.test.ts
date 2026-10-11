import { describe, expect, it } from "vitest";

import { parseSessionFrame } from "./session-events";
import type { NovaBackgroundTask } from "../types/nova";

function task(taskId: string): NovaBackgroundTask {
    return {
        task_id: taskId,
        kind: "shell",
        session_id: "s-1",
        label: "run",
        status: "running",
        background: true,
        created_at_ms: 1,
        started_at_ms: null,
        finished_at_ms: null,
        timeout_seconds: 30,
        exit_code: null,
        output_bytes: 0,
        output_truncated: false,
        result: "",
        error: null,
        progress: null,
        progress_message: null,
        last_activity_at_ms: null,
    };
}

describe("parseSessionFrame", () => {
    it("returns null for malformed JSON", () => {
        expect(parseSessionFrame("not json")).toBeNull();
    });

    it("returns null for non-object JSON bodies", () => {
        expect(parseSessionFrame("123")).toBeNull();
        expect(parseSessionFrame("null")).toBeNull();
        expect(parseSessionFrame('"snapshot"')).toBeNull();
    });

    it("returns null for an unknown frame type", () => {
        expect(parseSessionFrame(JSON.stringify({ type: "nope" }))).toBeNull();
        expect(parseSessionFrame(JSON.stringify({ foo: "bar" }))).toBeNull();
    });

    it("decodes a snapshot frame", () => {
        const frame = parseSessionFrame(
            JSON.stringify({
                type: "snapshot",
                active: ["a", "b"],
                tasks: [task("t-1")],
            }),
        );
        expect(frame).toEqual({
            type: "snapshot",
            active: ["a", "b"],
            tasks: [task("t-1")],
        });
    });

    it("defaults snapshot active and tasks to empty arrays when missing", () => {
        expect(parseSessionFrame(JSON.stringify({ type: "snapshot" }))).toEqual({
            type: "snapshot",
            active: [],
            tasks: [],
        });
    });

    it("ignores non-array snapshot active/tasks rather than passing them through", () => {
        expect(
            parseSessionFrame(
                JSON.stringify({ type: "snapshot", active: "a", tasks: 3 }),
            ),
        ).toEqual({ type: "snapshot", active: [], tasks: [] });
    });

    it("decodes a state delta frame", () => {
        expect(
            parseSessionFrame(
                JSON.stringify({
                    type: "state",
                    session_id: "s-1",
                    state: "active",
                }),
            ),
        ).toEqual({ type: "state", sessionId: "s-1", state: "active" });
    });

    it("drops a state frame missing session_id or state", () => {
        expect(
            parseSessionFrame(JSON.stringify({ type: "state", state: "active" })),
        ).toBeNull();
        expect(
            parseSessionFrame(
                JSON.stringify({ type: "state", session_id: "s-1" }),
            ),
        ).toBeNull();
    });

    it("decodes a task frame", () => {
        expect(
            parseSessionFrame(
                JSON.stringify({ type: "task", task: task("t-9") }),
            ),
        ).toEqual({ type: "task", task: task("t-9") });
    });

    it("drops a task frame with no task object", () => {
        expect(parseSessionFrame(JSON.stringify({ type: "task" }))).toBeNull();
        expect(
            parseSessionFrame(JSON.stringify({ type: "task", task: "x" })),
        ).toBeNull();
    });

    it("decodes a title frame", () => {
        expect(
            parseSessionFrame(
                JSON.stringify({
                    type: "title",
                    session_id: "s-2",
                    title: "Renamed",
                }),
            ),
        ).toEqual({ type: "title", sessionId: "s-2", title: "Renamed" });
    });

    it("drops a title frame missing session_id or title", () => {
        expect(
            parseSessionFrame(JSON.stringify({ type: "title", title: "x" })),
        ).toBeNull();
        expect(
            parseSessionFrame(
                JSON.stringify({ type: "title", session_id: "s-2" }),
            ),
        ).toBeNull();
    });
});
