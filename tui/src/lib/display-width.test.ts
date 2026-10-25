import { describe, expect, test } from "bun:test";
import { displayWidth, truncateEnd, truncateMiddle } from "./display-width.ts";

describe("displayWidth", () => {
    test("counts ASCII as one column", () => {
        expect(displayWidth("abc")).toBe(3);
    });

    test("counts CJK as two columns", () => {
        expect(displayWidth("中文")).toBe(4);
    });

    test("counts the status glyph as one column", () => {
        expect(displayWidth("●")).toBe(1);
    });
});

describe("truncateEnd", () => {
    test("keeps short text unchanged", () => {
        expect(truncateEnd("hello", 10)).toBe("hello");
    });

    test("adds an ellipsis within the budget", () => {
        expect(truncateEnd("hello", 4)).toBe("hel…");
        expect(displayWidth(truncateEnd("hello", 4))).toBe(4);
    });

    test("does not split a wide character", () => {
        const result = truncateEnd("中文中文", 5);
        expect(result).toBe("中文…");
        expect(displayWidth(result)).toBe(5);
    });
});

describe("truncateMiddle", () => {
    test("keeps both ends", () => {
        expect(truncateMiddle("abcdefghij", 5)).toBe("ab…ij");
    });

    test("fits CJK text by display width", () => {
        const result = truncateMiddle("中文中文中文", 7);
        expect(displayWidth(result)).toBeLessThanOrEqual(7);
        expect(result).toContain("…");
    });

    test("returns a single ellipsis for one column", () => {
        expect(truncateMiddle("abcdef", 1)).toBe("…");
    });
});
