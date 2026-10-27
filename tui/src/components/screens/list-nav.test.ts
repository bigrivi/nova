import { describe, expect, test } from "bun:test";

import { buildRows, rowOf } from "./list-nav.ts";

type Item = { provider: string; name: string };

const ITEMS: Item[] = [
    { provider: "A", name: "a1" },
    { provider: "A", name: "a2" },
    { provider: "B", name: "b1" },
    { provider: "B", name: "b2" },
    { provider: "C", name: "c1" },
];

const groupOf = (item: Item) => item.provider;

describe("buildRows", () => {
    test("is the item list unchanged without grouping", () => {
        const rows = buildRows(ITEMS);
        expect(rows).toHaveLength(ITEMS.length);
        expect(rows.every((row) => row.kind === "item")).toBe(true);
    });

    test("inserts a spacer and one header per group boundary", () => {
        const rows = buildRows(ITEMS, groupOf);
        expect(
            rows.map((row) => {
                if (row.kind === "header") return `#${row.label}`;
                if (row.kind === "spacer") return "";
                return row.item.name;
            }),
        ).toEqual([
            "#A",
            "a1",
            "a2",
            "",
            "#B",
            "b1",
            "b2",
            "",
            "#C",
            "c1",
        ]);
    });

    test("keeps item indices pointing at the filtered list", () => {
        const rows = buildRows(ITEMS, groupOf);
        const items = rows.filter((row) => row.kind === "item");
        expect(items.map((row) => row.index)).toEqual([0, 1, 2, 3, 4]);
    });
});

describe("rowOf", () => {
    test("finds the row that selects an item", () => {
        const rows = buildRows(ITEMS, groupOf);
        expect(rowOf(rows, 2)).toBe(5);
    });

    test("returns -1 for an item that is not rendered", () => {
        expect(rowOf(buildRows(ITEMS, groupOf), 99)).toBe(-1);
    });
});
