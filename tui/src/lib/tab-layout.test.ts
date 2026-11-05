import { describe, expect, test } from "bun:test";
import {
    adaptiveTabLayout,
    TAB_MAX_WIDTH,
    TAB_MIN_WIDTH,
    TAB_WIDTH,
    tabOverflowWidth,
    type TabLayoutItem,
} from "./tab-layout.ts";

const tabs = (count: number): TabLayoutItem[] =>
    Array.from({ length: count }, (_, index) => ({ id: String(index) }));

describe("tab layout", () => {
    test("shares roomy space equally and caps the total width", () => {
        const layout = adaptiveTabLayout(tabs(3), "0", 100);
        expect(layout.widths).toEqual([
            TAB_MAX_WIDTH,
            TAB_MAX_WIDTH,
            TAB_MAX_WIDTH,
        ]);
        expect(layout.total).toBe(96);
    });

    test("caps a single tab instead of stretching it", () => {
        const layout = adaptiveTabLayout([{ id: "a" }], "a", 100);
        expect(layout.widths).toEqual([TAB_MAX_WIDTH]);
    });

    test("expands only the active tab under compact pressure", () => {
        const layout = adaptiveTabLayout(tabs(7), "3", 76);
        expect(layout.widths).toEqual([9, 9, 9, TAB_WIDTH, 9, 9, 9]);
        expect(layout.widths.reduce((sum, width) => sum + width, 0)).toBe(
            layout.total,
        );
    });

    test("never goes below the readable minimum", () => {
        const layout = adaptiveTabLayout(tabs(6), "0", 40);
        expect(layout.widths.every((width) => width >= TAB_MIN_WIDTH)).toBe(
            true,
        );
    });

    test("shows overflow markers and a sticky window", () => {
        const all = tabs(10);
        const initial = adaptiveTabLayout(all, "3", 70);
        expect(initial.before).toBe(0);
        expect(initial.start).toBe(0);

        const inside = adaptiveTabLayout(all, "4", 70, initial.start);
        expect(inside.start).toBe(0);

        const crossed = adaptiveTabLayout(all, "7", 70, inside.start);
        expect(crossed.start).toBeGreaterThan(0);
        expect(crossed.visible.some((tab) => tab.id === "7")).toBe(true);
        expect(crossed.after).toBeGreaterThan(0);
    });

    test("reserves a gap beside the overflow digits", () => {
        expect(tabOverflowWidth(5)).toBe(3);
        expect(tabOverflowWidth(12)).toBe(4);
    });

    test("returns an empty layout for no tabs", () => {
        expect(adaptiveTabLayout([], null, 80)).toEqual({
            visible: [],
            widths: [],
            before: 0,
            after: 0,
            start: 0,
            total: 0,
        });
    });
});
