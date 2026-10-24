import { describe, expect, test } from "bun:test";
import { loadList, resolveInitialIndex } from "./use-list-screen.ts";

describe("loadList", () => {
    test("returns the loader's items", async () => {
        expect(await loadList(async () => [1, 2, 3])).toEqual({
            items: [1, 2, 3],
            error: "",
        });
    });

    test("captures an Error message", async () => {
        expect(
            await loadList(async () => {
                throw new Error("boom");
            }),
        ).toEqual({ items: [], error: "boom" });
    });

    test("captures a non-Error rejection", async () => {
        expect(
            await loadList(async () => {
                throw "nope";
            }),
        ).toEqual({ items: [], error: "nope" });
    });
});

describe("resolveInitialIndex", () => {
    const items = ["a", "b", "c"];

    test("returns the preselected index", () => {
        expect(resolveInitialIndex(items, (list) => list.indexOf("b"))).toBe(1);
    });

    test("clamps to zero when nothing matches", () => {
        expect(resolveInitialIndex(items, () => -1)).toBe(0);
    });

    test("clamps to the last index when out of range", () => {
        expect(resolveInitialIndex(items, () => 99)).toBe(2);
    });

    test("returns zero for an empty list", () => {
        expect(resolveInitialIndex([], () => 3)).toBe(0);
    });

    test("returns zero without a preselection", () => {
        expect(resolveInitialIndex(items)).toBe(0);
    });
});
