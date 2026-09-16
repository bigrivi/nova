import { describe, expect, it } from "vitest";

import {
    isThreadRunning,
    nextRunningMap,
    runningThreadIds,
} from "./thread-running";

describe("nextRunningMap", () => {
    it("marks one thread running without touching the others", () => {
        const next = nextRunningMap({ a: true }, "b", true);
        expect(next).toEqual({ a: true, b: true });
    });

    it("removes the key when a thread stops", () => {
        const next = nextRunningMap({ a: true, b: true }, "a", false);
        expect(next).toEqual({ b: true });
        expect("a" in next).toBe(false);
    });

    it("returns the same reference when nothing changes", () => {
        const previous = { a: true };
        expect(nextRunningMap(previous, "a", true)).toBe(previous);
        expect(nextRunningMap(previous, "b", false)).toBe(previous);
    });
});

describe("isThreadRunning / runningThreadIds", () => {
    it("reports per-thread state for parallel sessions", () => {
        const running = nextRunningMap(
            nextRunningMap({}, "a", true),
            "b",
            true,
        );
        expect(isThreadRunning(running, "a")).toBe(true);
        expect(isThreadRunning(running, "b")).toBe(true);
        expect(isThreadRunning(running, "c")).toBe(false);

        const stopped = nextRunningMap(running, "a", false);
        expect(isThreadRunning(stopped, "a")).toBe(false);
        expect(isThreadRunning(stopped, "b")).toBe(true);
        expect(runningThreadIds(stopped)).toEqual(["b"]);
    });
});
