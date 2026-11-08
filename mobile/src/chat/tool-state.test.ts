import { describe, expect, test } from "bun:test";

import { readToolState, toolStateLabel } from "./tool-state";

describe("tool state", () => {
    test("a pending approval wins over a running call", () => {
        expect(
            readToolState({ status: "running", waiting: true }),
        ).toBe("waiting");
        expect(toolStateLabel("waiting")).toBe("waiting for approval");
    });

    test("a live background task outlives the returned handle", () => {
        expect(
            readToolState({ status: "done", taskStatus: "running" }),
        ).toBe("running");
        expect(
            readToolState({ status: "done", taskStatus: "succeeded" }),
        ).toBe("done");
        expect(
            readToolState({ status: "done", taskStatus: "timed_out" }),
        ).toBe("error");
        expect(
            readToolState({ status: "done", taskStatus: "cancelled" }),
        ).toBe("cancelled");
        expect(
            readToolState({ status: "done", taskStatus: "interrupted" }),
        ).toBe("cancelled");
    });

    test("without a task, the call's own status decides", () => {
        expect(readToolState({ status: "running" })).toBe("running");
        expect(readToolState({ status: "done" })).toBe("done");
        expect(readToolState({ status: "error" })).toBe("error");
    });
});
