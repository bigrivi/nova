import { describe, expect, test } from "bun:test";

import { breath, hintAt, TICK_MS } from "./launch.ts";

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

describe("hintAt", () => {
    const options = ["a", "b", "c"];

    test("walks the list and wraps around", () => {
        expect(hintAt(0, options)).toBe("a");
        expect(hintAt(1, options)).toBe("b");
        expect(hintAt(2, options)).toBe("c");
        expect(hintAt(3, options)).toBe("a");
    });

    test("is empty for an empty list", () => {
        expect(hintAt(5, [])).toBe("");
    });

    test("ticks fast enough to look smooth", () => {
        expect(TICK_MS).toBeLessThanOrEqual(250);
    });
});
