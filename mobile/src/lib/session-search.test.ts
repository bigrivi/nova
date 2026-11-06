import { describe, expect, test } from "bun:test";

import { filterSessionsByTitle } from "./session-search";

const sessions = [
    { title: "Tokyo trip" },
    { title: "refactor notes" },
    { title: null },
];

describe("session search", () => {
    test("matches case-insensitively and keeps order", () => {
        expect(
            filterSessionsByTitle(sessions, "TOKYO").map((s) => s.title),
        ).toEqual(["Tokyo trip"]);
        expect(filterSessionsByTitle(sessions, "o").map((s) => s.title)).toEqual(
            ["Tokyo trip", "refactor notes"],
        );
    });

    test("blank or padding-only queries keep everything", () => {
        expect(filterSessionsByTitle(sessions, "   ")).toHaveLength(3);
    });

    test("untitled sessions never match a non-blank query", () => {
        expect(filterSessionsByTitle(sessions, "session")).toEqual([]);
    });
});
