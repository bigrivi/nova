import { describe, expect, test } from "bun:test";
import {
    marqueeCycleWidth,
    marqueeFrame,
    marqueeOverflows,
    sliceByWidth,
    takeWidth,
} from "./marquee.ts";
import { displayWidth } from "./display-width.ts";

describe("marquee", () => {
    test("counts display columns, not code units", () => {
        expect(displayWidth("中文")).toBe(4);
        expect(takeWidth("中文abc", 5)).toBe("中文a");
        expect(displayWidth(takeWidth("中文abc", 5))).toBe(5);
    });

    test("slices a window by columns", () => {
        expect(sliceByWidth("abcdef", 2, 2)).toBe("cd");
        expect(sliceByWidth("中文中文", 2, 0)).toBe("中");
        expect(sliceByWidth("中文中文", 2, 2)).toBe("文");
        expect(sliceByWidth("中文中文", 2, 1)).toBe("文");
    });

    test("detects overflow", () => {
        expect(marqueeOverflows("short", 4)).toBe(true);
        expect(marqueeOverflows("short", 5)).toBe(false);
        expect(marqueeOverflows("short", 10)).toBe(false);
    });

    test("returns the title unchanged when it fits", () => {
        expect(marqueeFrame("title", 10, 0)).toBe("title");
        expect(marqueeFrame("title", 10, 3)).toBe("title");
    });

    test("loops through the separator", () => {
        const cycle = marqueeCycleWidth("opencode");
        expect(cycle).toBe(displayWidth("opencode · "));
        expect(marqueeFrame("opencode", 4, 0)).toBe("open");
        expect(marqueeFrame("opencode", 4, 8)).toBe(" · o");
        expect(marqueeFrame("opencode", 4, cycle + 1)).toBe("penc");
    });

    test("stays empty for a zero-width window", () => {
        expect(marqueeFrame("title", 0, 1)).toBe("");
        expect(takeWidth("title", 0)).toBe("");
    });
});
