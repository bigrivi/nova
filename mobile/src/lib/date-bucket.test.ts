import { describe, expect, test } from "bun:test";

import { dateBucket } from "./date-bucket";

const now = new Date(2026, 10, 5, 12, 0, 0); // 2026-11-05 12:00 local

describe("date buckets", () => {
    test("today starts at local midnight", () => {
        expect(dateBucket(new Date(2026, 10, 5, 0, 1).getTime(), now)).toBe(
            "today",
        );
        expect(dateBucket(new Date(2026, 10, 4, 23, 59).getTime(), now)).toBe(
            "yesterday",
        );
    });

    test("yesterday and last seven days", () => {
        expect(dateBucket(new Date(2026, 10, 3, 12).getTime(), now)).toBe(
            "last7Days",
        );
        expect(dateBucket(new Date(2026, 9, 30, 12).getTime(), now)).toBe(
            "last7Days",
        );
        expect(dateBucket(new Date(2026, 9, 28, 12).getTime(), now)).toBe(
            "older",
        );
    });
});
