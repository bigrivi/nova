import { beforeEach, describe, expect, test } from "bun:test";
import {
    clearInputHistory,
    historyDown,
    historyUp,
    isNavigatingHistory,
    rememberInput,
    resetHistoryCursor,
} from "./input-history.ts";

describe("input history", () => {
    beforeEach(() => {
        clearInputHistory();
    });

    test("recalls the previous prompt", () => {
        rememberInput("first");
        rememberInput("second");
        expect(historyUp("")).toBe("second");
        expect(historyUp("second")).toBe("first");
    });

    test("stops at the oldest entry", () => {
        rememberInput("only");
        expect(historyUp("")).toBe("only");
        expect(historyUp("only")).toBeNull();
    });

    test("down restores the draft that was being typed", () => {
        rememberInput("first");
        rememberInput("second");
        expect(historyUp("half-typed")).toBe("second");
        expect(historyDown()).toBe("half-typed");
    });

    test("down without recall is not handled", () => {
        rememberInput("first");
        expect(historyDown()).toBeNull();
    });

    test("typing resets the position", () => {
        rememberInput("first");
        rememberInput("second");
        historyUp("");
        resetHistoryCursor();
        expect(historyUp("new")).toBe("second");
    });

    test("blank and repeated entries are dropped", () => {
        rememberInput("");
        rememberInput("   ");
        rememberInput("same");
        rememberInput("same");
        expect(historyUp("")).toBe("same");
        expect(historyUp("same")).toBeNull();
    });

    test("empty history has nothing to recall", () => {
        expect(historyUp("")).toBeNull();
    });

    test("stays in recall after loading a multi-line prompt", () => {
        rememberInput("line one\nline two");
        expect(historyUp("")).toBe("line one\nline two");
        expect(isNavigatingHistory()).toBe(true);
        resetHistoryCursor();
        expect(isNavigatingHistory()).toBe(false);
    });
});
