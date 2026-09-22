import { describe, expect, it } from "vitest";

import { consumeParkedTail, decideTailOnActive } from "./thread-tail";

describe("decideTailOnActive", () => {
    it("tails immediately for the open thread with no local stream", () => {
        expect(
            decideTailOnActive({
                active: true,
                current: true,
                localStream: false,
                ownTurn: false,
            }),
        ).toBe("tail-now");
    });

    it("parks when the open thread still has a draining local stream", () => {
        expect(
            decideTailOnActive({
                active: true,
                current: true,
                localStream: true,
                ownTurn: false,
            }),
        ).toBe("park");
    });

    it("ignores background threads (lighting only)", () => {
        expect(
            decideTailOnActive({
                active: true,
                current: false,
                localStream: false,
                ownTurn: false,
            }),
        ).toBe("ignore");
    });

    it("ignores idle events (no tail decision on teardown)", () => {
        expect(
            decideTailOnActive({
                active: false,
                current: true,
                localStream: false,
                ownTurn: false,
            }),
        ).toBe("ignore");
    });

    it("ignores the client's own turn (no self-park, no spurious resume)", () => {
        expect(
            decideTailOnActive({
                active: true,
                current: true,
                localStream: true,
                ownTurn: true,
            }),
        ).toBe("ignore");
    });
});

describe("consumeParkedTail", () => {
    it("returns the thread id when parked and still current", () => {
        const parked = new Set(["t1"]);
        expect(consumeParkedTail(parked, "t1", true)).toBe("t1");
    });

    it("returns null when nothing was parked", () => {
        expect(consumeParkedTail(new Set(), "t1", true)).toBeNull();
    });

    it("clears the flag without tailing after a thread switch", () => {
        const parked = new Set(["t1"]);
        expect(consumeParkedTail(parked, "t1", false)).toBeNull();
        expect(parked.size).toBe(0);
    });

    it("consumes exactly once", () => {
        const parked = new Set(["t1"]);
        expect(consumeParkedTail(parked, "t1", true)).toBe("t1");
        expect(consumeParkedTail(parked, "t1", true)).toBeNull();
    });
});

describe("bug scenario: active arrives while the local stream drains", () => {
    it("parks on the event, then tails once at cleanup", () => {
        const parked = new Set<string>();
        const tailed: string[] = [];
        const tail = (tid: string) => {
            tailed.push(tid);
        };

        // 1. wake turn goes active; open thread; local stream of the
        //    previous turn still draining -> park, do NOT tail now.
        const decision = decideTailOnActive({
            active: true,
            current: true,
            localStream: true,
            ownTurn: false,
        });
        expect(decision).toBe("park");
        if (decision === "park") {
            parked.add("t1");
        }
        expect(tailed).toEqual([]);

        // 2. a duplicate active edge before cleanup stays parked, no tail.
        expect(
            decideTailOnActive({
                active: true,
                current: true,
                localStream: true,
                ownTurn: false,
            }),
        ).toBe("park");

        // 3. local stream cleanup consumes the flag exactly once.
        const first = consumeParkedTail(parked, "t1", true);
        if (first !== null) {
            tail(first);
        }
        expect(tailed).toEqual(["t1"]);
        expect(consumeParkedTail(parked, "t1", true)).toBeNull();
        expect(tailed).toEqual(["t1"]);
    });

    it("direct tail when no local stream is open (idle-parent case)", () => {
        const parked = new Set<string>();
        expect(
            decideTailOnActive({
                active: true,
                current: true,
                localStream: false,
                ownTurn: false,
            }),
        ).toBe("tail-now");
        expect(consumeParkedTail(parked, "t1", true)).toBeNull();
    });
});
