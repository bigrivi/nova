import { describe, expect, test } from "bun:test";
import { relativeAge } from "./RewindScreen.tsx";

describe("relativeAge", () => {
    test("counts seconds, minutes, then hours", () => {
        const now = Date.now();
        expect(relativeAge(now - 5_000)).toBe("5s ago");
        expect(relativeAge(now - 90_000)).toBe("2m ago");
        expect(relativeAge(now - 7_200_000)).toBe("2h ago");
    });

    test("never goes negative on a clock that disagrees", () => {
        expect(relativeAge(Date.now() + 60_000)).toBe("0s ago");
    });
});
