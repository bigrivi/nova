import { describe, expect, test } from "bun:test";
import { loadList } from "./use-list-screen.ts";

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
