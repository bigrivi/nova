import { describe, expect, test } from "bun:test";

import { breath, placeholderAt, TICK_MS } from "./launch.ts";

describe("breath", () => {
    test("starts dark, peaks in the middle and comes back", () => {
        expect(breath(0)).toBe(0);
        expect(breath(12)).toBeCloseTo(1, 5);
        expect(breath(24)).toBe(0);
    });

    test("stays within 0..1 on every tick", () => {
        for (let tick = 0; tick < 100; tick += 1) {
            const value = breath(tick);
            expect(value).toBeGreaterThanOrEqual(0);
            expect(value).toBeLessThanOrEqual(1);
        }
    });
});

describe("placeholderAt", () => {
    const options = ["a", "b", "c"];

    test("holds each placeholder for a while, then advances", () => {
        expect(placeholderAt(0, options)).toBe("a");
        expect(placeholderAt(31, options)).toBe("a");
        expect(placeholderAt(32, options)).toBe("b");
        expect(placeholderAt(64, options)).toBe("c");
        expect(placeholderAt(96, options)).toBe("a");
    });

    test("is empty for an empty list", () => {
        expect(placeholderAt(5, [])).toBe("");
    });

    test("ticks fast enough to look smooth", () => {
        expect(TICK_MS).toBeLessThanOrEqual(250);
    });
});
