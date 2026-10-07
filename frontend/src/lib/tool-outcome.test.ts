import type { ToolCallMessagePartStatus } from "@assistant-ui/react";
import { describe, expect, it } from "vitest";

import type { NovaBackgroundTaskStatus } from "@/types/nova";

import { readToolOutcome } from "./tool-outcome";

type Status = ToolCallMessagePartStatus | undefined;
type Background = NovaBackgroundTaskStatus | null;

const STATUSES: readonly Status[] = [
    undefined,
    { type: "complete" },
    { type: "running" },
    { type: "requires-action", reason: "tool-calls" },
    { type: "requires-action", reason: "interrupt" },
    { type: "incomplete", reason: "cancelled" },
    { type: "incomplete", reason: "error", error: "boom" },
    { type: "incomplete", reason: "other" },
];

const BACKGROUNDS: readonly Background[] = [
    null,
    "queued",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
];

const ERRORS: readonly (boolean | undefined)[] = [undefined, false, true];

/**
 * The two inlined derivations this helper replaced, kept verbatim as the
 * oracle: one in the trigger (background task aware) and one in the content
 * (background task deliberately excluded).
 */
function triggerOriginal(
    status: Status,
    isError: boolean | undefined,
    backgroundState: Background,
) {
    const statusType = status?.type ?? "complete";
    const taskRunning =
        backgroundState === "queued" || backgroundState === "running";
    const taskFailed =
        backgroundState === "failed" || backgroundState === "timed_out";
    const taskCancelled = backgroundState === "cancelled";
    const isRunning = statusType === "running" || taskRunning;
    const isCancelled =
        (status?.type === "incomplete" && status.reason === "cancelled") ||
        taskCancelled;
    const statusError =
        status?.type === "incomplete" && !isCancelled && status.error != null;
    return {
        isRunning,
        isCancelled,
        errored:
            (isError === true || statusError || taskFailed) && !taskRunning,
    };
}

function contentOriginal(status: Status, isError: boolean | undefined) {
    const isCancelled =
        status?.type === "incomplete" && status.reason === "cancelled";
    return {
        isCancelled,
        errored:
            isError === true ||
            (status?.type === "incomplete" && !isCancelled &&
                status.error != null),
    };
}

describe("readToolOutcome matches the derivations it replaced", () => {
    it("agrees with the trigger derivation across the whole input space", () => {
        let cases = 0;
        for (const status of STATUSES) {
            for (const isError of ERRORS) {
                for (const backgroundState of BACKGROUNDS) {
                    expect(
                        readToolOutcome(status, isError, backgroundState),
                    ).toStrictEqual(
                        triggerOriginal(status, isError, backgroundState),
                    );
                    cases += 1;
                }
            }
        }
        expect(cases).toBe(STATUSES.length * ERRORS.length * BACKGROUNDS.length);
    });

    it("agrees with the content derivation when no task is passed", () => {
        for (const status of STATUSES) {
            for (const isError of ERRORS) {
                const { isCancelled, errored } = readToolOutcome(
                    status,
                    isError,
                    null,
                );
                expect({ isCancelled, errored }).toStrictEqual(
                    contentOriginal(status, isError),
                );
            }
        }
    });
});

describe("readToolOutcome resolves the states the UI depends on", () => {
    it("treats a plain finished tool call as settled and clean", () => {
        expect(readToolOutcome({ type: "complete" }, false, null)).toStrictEqual(
            { isRunning: false, isCancelled: false, errored: false },
        );
    });

    it("keeps a live background task out of the errored state", () => {
        expect(readToolOutcome({ type: "complete" }, true, "running")).toStrictEqual(
            { isRunning: true, isCancelled: false, errored: false },
        );
    });

    it("surfaces a background task that fails after its handle returned", () => {
        expect(readToolOutcome({ type: "complete" }, false, "failed")).toStrictEqual(
            { isRunning: false, isCancelled: false, errored: true },
        );
        expect(
            readToolOutcome({ type: "complete" }, false, "timed_out"),
        ).toStrictEqual({
            isRunning: false,
            isCancelled: false,
            errored: true,
        });
    });

    it("separates a cancelled call from a failed one", () => {
        expect(
            readToolOutcome({ type: "incomplete", reason: "cancelled" }, false, null),
        ).toStrictEqual({
            isRunning: false,
            isCancelled: true,
            errored: false,
        });
        expect(
            readToolOutcome(
                { type: "incomplete", reason: "error", error: "boom" },
                false,
                null,
            ),
        ).toStrictEqual({
            isRunning: false,
            isCancelled: false,
            errored: true,
        });
    });

    it("does not treat a finished task as a failure", () => {
        expect(
            readToolOutcome({ type: "complete" }, false, "succeeded"),
        ).toStrictEqual({
            isRunning: false,
            isCancelled: false,
            errored: false,
        });
    });

    it("reads a missing part status as finished, not running", () => {
        expect(readToolOutcome(undefined, undefined, null)).toStrictEqual({
            isRunning: false,
            isCancelled: false,
            errored: false,
        });
    });
});