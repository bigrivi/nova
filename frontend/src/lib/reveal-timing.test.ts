import { describe, expect, it } from "vitest";

import {
    REVEAL_VELOCITY_PX_PER_SECOND,
    revealDurationSeconds,
} from "./reveal-timing";

describe("revealDurationSeconds", () => {
    it("returns zero when the title fits", () => {
        expect(revealDurationSeconds(0)).toBe(0);
        expect(revealDurationSeconds(-40)).toBe(0);
    });

    it("holds a constant pace across the range", () => {
        for (const overflow of [113, 159, 226, 327, 350]) {
            expect(overflow / revealDurationSeconds(overflow)).toBeCloseTo(
                REVEAL_VELOCITY_PX_PER_SECOND,
                6,
            );
        }
    });

    it("slows short overflows to the floor instead of blinking", () => {
        const floorEdge = 0.9 * REVEAL_VELOCITY_PX_PER_SECOND;
        expect(revealDurationSeconds(20)).toBe(0.9);
        expect(revealDurationSeconds(floorEdge)).toBe(0.9);
    });

    it("keeps long overflows at the same pace rather than capping them", () => {
        for (const overflow of [400, 2000]) {
            expect(overflow / revealDurationSeconds(overflow)).toBeCloseTo(
                REVEAL_VELOCITY_PX_PER_SECOND,
                6,
            );
        }
    });

    it("never shortens the duration as the text gets longer", () => {
        let previous = 0;
        for (let overflow = 0; overflow <= 800; overflow += 25) {
            const duration = revealDurationSeconds(overflow);
            expect(duration).toBeGreaterThanOrEqual(previous);
            previous = duration;
        }
    });
});
