import { describe, expect, test } from "bun:test";
import { deriveAgentStatus, lastAssistantStatus } from "./status.ts";

describe("deriveAgentStatus", () => {
    const base = {
        isStreaming: false,
        hasApproval: false,
        hasQuestion: false,
    };

    test("is idle by default", () => {
        expect(deriveAgentStatus(base)).toBe("idle");
    });

    test("waits on approvals and questions first", () => {
        expect(
            deriveAgentStatus({
                ...base,
                isStreaming: true,
                hasApproval: true,
            }),
        ).toBe("waiting");
        expect(deriveAgentStatus({ ...base, hasQuestion: true })).toBe(
            "waiting",
        );
    });

    test("runs while streaming", () => {
        expect(deriveAgentStatus({ ...base, isStreaming: true })).toBe(
            "running",
        );
    });

    test("reports the last failure when idle", () => {
        expect(
            deriveAgentStatus({ ...base, lastAssistantStatus: "error" }),
        ).toBe("error");
    });

    test("streaming wins over an earlier failure", () => {
        expect(
            deriveAgentStatus({
                ...base,
                isStreaming: true,
                lastAssistantStatus: "error",
            }),
        ).toBe("running");
    });
});

describe("lastAssistantStatus", () => {
    const message = (role: "user" | "assistant", status: "done" | "error") => ({
        role,
        status,
    });

    test("finds the newest assistant message", () => {
        expect(
            lastAssistantStatus([
                message("assistant", "done"),
                message("user", "done"),
                message("assistant", "error"),
            ]),
        ).toBe("error");
    });

    test("returns undefined without an assistant message", () => {
        expect(lastAssistantStatus([message("user", "done")])).toBeUndefined();
    });
});
