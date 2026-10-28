import { describe, expect, test } from "bun:test";
import {
    RESULT_LIMITS,
    cleanLines,
    sanitizeInline,
    sanitizeOutput,
    displayWidth,
    tailLines,
    truncateMiddle,
    truncateToWidth,
} from "./text.ts";

describe("format/text", () => {
    test("displayWidth counts CJK as two columns", () => {
        expect(displayWidth("ab")).toBe(2);
        expect(displayWidth("你好")).toBe(4);
    });

    test("truncateToWidth keeps display width", () => {
        expect(truncateToWidth("abcdefghij", 5)).toBe("abcd…");
        expect(truncateToWidth("你好世界", 5)).toBe("你好…");
    });

    test("cleanLines drops leading and trailing blanks", () => {
        expect(cleanLines("\n \n7 files\n\n")).toEqual(["7 files"]);
    });

    test("tailLines returns the last n lines", () => {
        expect(tailLines("a\nb\nc\nd\n", 2)).toEqual(["c", "d"]);
        expect(tailLines("only", 2)).toEqual(["only"]);
        expect(tailLines("", 2)).toEqual([]);
    });

    test("truncateMiddle keeps both ends", () => {
        expect(truncateMiddle("/a/very/long/path/to/file.ts", 12)).toContain("…");
        expect(displayWidth(truncateMiddle("/a/very/long/path/to/file.ts", 12))).toBeLessThanOrEqual(12);
    });

    test("sanitizeOutput drops terminal control sequences", () => {
        // OSC 52 writes the clipboard; CSI clears the screen / moves the cursor.
        expect(sanitizeOutput("a\x1b]52;c;AAAA\x07b")).toBe("ab");
        expect(sanitizeOutput("a\x1b]0;title\x1b\\b")).toBe("ab");
        expect(sanitizeOutput("a\x1b[2Jb")).toBe("ab");
        expect(sanitizeOutput("a\x1b[1A\x1b[2Kb")).toBe("ab");
        expect(sanitizeOutput("a\x1b[?25lb")).toBe("ab");
        expect(sanitizeOutput("a\x1bPq#0;2;0;0;0\x1b\\b")).toBe("ab");
        expect(sanitizeOutput("a\x1bb")).toBe("ab");
    });

    test("sanitizeOutput keeps the last frame of a progress line", () => {
        expect(sanitizeOutput("10%\r20%\r100%")).toBe("100%");
    });

    test("sanitizeOutput normalises CRLF, tabs and stray controls", () => {
        expect(sanitizeOutput("a\r\nb")).toBe("a\nb");
        expect(sanitizeOutput("a\tb")).toBe("a    b");
        expect(sanitizeOutput("a\x07b\x7fc")).toBe("abc");
    });

    test("sanitizeOutput leaves visible Unicode alone", () => {
        expect(sanitizeOutput("你好 · emoji 🚀 e\u0301")).toBe("你好 · emoji 🚀 e\u0301");
    });

    test("sanitizeInline collapses newlines and trims", () => {
        expect(sanitizeInline("  npm\n test  ")).toBe("npm test");
        expect(sanitizeInline("x\x1b[2Jy")).toBe("xy");
    });

    test("cleanLines and tailLines share the sanitiser", () => {
        expect(cleanLines("\x1b[31mred\x1b[0m\r\n\r\nnext")).toEqual(["red", "", "next"]);
        expect(tailLines("a\x1b[2J\nb\r\nc", 2)).toEqual(["b", "c"]);
    });

    test("result limits are centralized", () => {
        expect(RESULT_LIMITS.shellOk).toBe(3);
        expect(RESULT_LIMITS.expandedMax).toBe(200);
    });
});