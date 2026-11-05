import { describe, expect, test } from "bun:test";

import { parseTodos } from "./todo";

describe("todo parsing", () => {
    test("accepts an object, an array and a JSON string", () => {
        const items = [
            { content: "one", status: "completed" },
            { content: "two", status: "in_progress" },
        ];
        expect(parseTodos({ todos: items })).toHaveLength(2);
        expect(parseTodos(items)).toHaveLength(2);
        expect(parseTodos(JSON.stringify({ todos: items }))).toHaveLength(2);
    });

    test("normalizes unknown statuses and drops empty rows", () => {
        expect(
            parseTodos([
                { content: "a", status: "weird" },
                { content: "  " },
            ]),
        ).toEqual([{ content: "a", status: "pending" }]);
    });

    test("malformed input is empty", () => {
        expect(parseTodos(null)).toEqual([]);
        expect(parseTodos("not json")).toEqual([]);
        expect(parseTodos({ nope: true })).toEqual([]);
    });
});
