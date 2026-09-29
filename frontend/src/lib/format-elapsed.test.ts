import { describe, expect, it } from "vitest";

import { formatElapsed } from "./format-elapsed";

describe("formatElapsed", () => {
    const start = 1_000_000;

    it("pads seconds and minutes", () => {
        expect(formatElapsed(start, start)).toBe("00:00");
        expect(formatElapsed(start, start + 5_000)).toBe("00:05");
        expect(formatElapsed(start, start + 65_000)).toBe("01:05");
        expect(formatElapsed(start, start + 600_000)).toBe("10:00");
    });

    it("truncates partial seconds instead of rounding up", () => {
        expect(formatElapsed(start, start + 1_999)).toBe("00:01");
    });

    it("keeps counting past an hour rather than wrapping", () => {
        expect(formatElapsed(start, start + 3_725_000)).toBe("62:05");
    });

    it("clamps a clock that went backwards", () => {
        expect(formatElapsed(start, start - 5_000)).toBe("00:00");
    });
});
