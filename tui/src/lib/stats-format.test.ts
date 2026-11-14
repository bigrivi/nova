import { describe, expect, test } from "bun:test";
import { compactTokens, formatCost, formatDuration } from "./stats-format.ts";

describe("compactTokens", () => {
    test("keeps small counts as they are", () => {
        expect(compactTokens(0)).toBe("0");
        expect(compactTokens(512)).toBe("512");
    });

    test("shortens thousands and millions", () => {
        expect(compactTokens(1_200)).toBe("1.2K");
        expect(compactTokens(42_100_000)).toBe("42.1M");
        expect(compactTokens(1_200_000_000)).toBe("1.2B");
    });

    test("drops a zero decimal", () => {
        expect(compactTokens(3_000_000)).toBe("3M");
        expect(compactTokens(20_000)).toBe("20K");
    });
});

describe("formatCost", () => {
    test("a known price reads as money", () => {
        expect(formatCost(4.82)).toBe("$4.82");
        expect(formatCost(0.5)).toBe("$0.50");
    });

    test("free is a real answer, not a missing one", () => {
        expect(formatCost(0)).toBe("$0.00");
    });

    test("a nonzero amount below a cent says so", () => {
        expect(formatCost(0.001)).toBe("<$0.01");
    });

    test("unknown is a dash, never zero", () => {
        expect(formatCost(undefined)).toBe("—");
    });
});

describe("formatDuration", () => {
    test("seconds, minutes, hours", () => {
        expect(formatDuration(48_000)).toBe("48s");
        expect(formatDuration(12 * 60_000)).toBe("12m");
        expect(formatDuration((4 * 60 + 12) * 60_000)).toBe("4h 12m");
    });
});
