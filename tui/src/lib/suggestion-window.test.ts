import { describe, expect, test } from "bun:test";
import { windowAround } from "./suggestion-window.ts";

describe("windowAround", () => {
    test("keeps a short list fully visible", () => {
        expect(windowAround(0, 3)).toEqual({
            start: 0,
            hiddenAbove: 0,
            hiddenBelow: 0,
        });
    });

    test("follows the cursor past the fold", () => {
        // The reported bug: item 9 of 20 was selectable but never drawn.
        const window = windowAround(9, 20);
        expect(window.start).toBe(7);
        expect(window.hiddenAbove).toBe(7);
        expect(window.hiddenBelow).toBe(7);
    });

    test("clamps at the end of the list", () => {
        expect(windowAround(19, 20).start).toBe(14);
        expect(windowAround(19, 20).hiddenBelow).toBe(0);
    });

    test("clamps at the start", () => {
        expect(windowAround(0, 20).start).toBe(0);
        expect(windowAround(1, 20).hiddenAbove).toBe(0);
    });

    test("is empty for an empty list", () => {
        expect(windowAround(0, 0)).toEqual({
            start: 0,
            hiddenAbove: 0,
            hiddenBelow: 0,
        });
    });
});
