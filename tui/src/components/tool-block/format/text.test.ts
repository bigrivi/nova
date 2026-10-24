import { describe, expect, test } from "bun:test";
import {
    RESULT_LIMITS,
    cleanLines,
    displayWidth,
    tailLines,
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

    test("result limits are centralized", () => {
        expect(RESULT_LIMITS.shellOk).toBe(3);
        expect(RESULT_LIMITS.expandedMax).toBe(200);
    });
});