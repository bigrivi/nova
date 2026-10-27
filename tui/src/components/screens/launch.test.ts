import { describe, expect, test } from "bun:test";

import { breath, buildHints, hintAt, HINTS, motionEnabled, TICK_MS } from "./launch.ts";

describe("breath", () => {
    test("starts dark, peaks in the middle and comes back", () => {
        expect(breath(0)).toBe(0);
        expect(breath(12)).toBeCloseTo(1, 5);
        expect(breath(24)).toBe(0);
    });

    test("eases at both ends", () => {
        // cosine, not a triangle: the first step is smaller than the middle one
        expect(breath(1) - breath(0)).toBeLessThan(breath(7) - breath(6));
    });

    test("stays within 0..1 on every tick", () => {
        for (let tick = 0; tick < 100; tick += 1) {
            const value = breath(tick);
            expect(value).toBeGreaterThanOrEqual(0);
            expect(value).toBeLessThanOrEqual(1);
        }
    });
});

describe("hintAt", () => {
    const options = ["a", "b", "c"];

    test("walks the list and wraps around", () => {
        expect(hintAt(0, options)).toBe("a");
        expect(hintAt(1, options)).toBe("b");
        expect(hintAt(3, options)).toBe("a");
    });

    test("is empty for an empty list", () => {
        expect(hintAt(5, [])).toBe("");
    });

    test("ticks fast enough to look smooth", () => {
        expect(TICK_MS).toBeLessThanOrEqual(250);
    });
});

describe("motionEnabled", () => {
    test("runs by default", () => {
        expect(motionEnabled({})).toBe(true);
    });

    test("stands still for NO_COLOR and NOVA_MOTION=0", () => {
        expect(motionEnabled({ NO_COLOR: "1" })).toBe(false);
        expect(motionEnabled({ NOVA_MOTION: "0" })).toBe(false);
        expect(motionEnabled({ NOVA_MOTION: "1" })).toBe(true);
    });
});

describe("buildHints", () => {
    test("falls back to the plain hints without saved sessions", () => {
        expect(buildHints(0)).toEqual([...HINTS]);
    });

    test("leads with the saved session count", () => {
        expect(buildHints(1)[0]).toBe("1 saved session · /sessions to resume");
        expect(buildHints(4)[0]).toBe("4 saved sessions · /sessions to resume");
        expect(buildHints(4).slice(1)).toEqual([...HINTS]);
    });
});
