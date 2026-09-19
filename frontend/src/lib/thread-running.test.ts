import { describe, expect, it } from "vitest";

import {
    isThreadRunning,
    nextRunningMap,
    reconcileRunningMap,
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

describe("reconcileRunningMap", () => {
    const noLocal = () => false;

    it("lights server-reported sessions without touching the others", () => {
        const next = reconcileRunningMap(
            { a: true },
            new Set(["a", "b"]),
            new Set(["a"]),
            noLocal,
        );
        expect(next).toEqual({ a: true, b: true });
    });

    it("turns off a watched session that disappears with no local stream", () => {
        const next = reconcileRunningMap(
            { a: true, b: true },
            new Set(["a"]),
            new Set(["a", "b"]),
            noLocal,
        );
        expect(next).toEqual({ a: true });
        expect("b" in next).toBe(false);
    });

    it("never flickers off a just-submitted session absent from snapshots", () => {
        const next = reconcileRunningMap(
            { fresh: true },
            new Set(),
            new Set(),
            noLocal,
        );
        expect(next).toEqual({ fresh: true });
    });

    it("keeps a disappeared session that still has a local stream", () => {
        const next = reconcileRunningMap(
            { a: true },
            new Set(),
            new Set(["a"]),
            (threadId) => threadId === "a",
        );
        expect(next).toEqual({ a: true });
    });

    it("returns the same reference when nothing changes", () => {
        const previous = { a: true };
        expect(
            reconcileRunningMap(previous, new Set(["a"]), new Set(["a"]), noLocal),
        ).toBe(previous);
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
