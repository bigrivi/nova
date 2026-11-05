import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
    useApprovalStore,
    type ApprovalPending,
} from "./approval-store.ts";

function pending(
    requestId: string,
    runId: number,
    sessionId = "s1",
): ApprovalPending {
    return {
        sessionId,
        requestId,
        command: "ls",
        description: "",
        toolName: "shell",
        rememberable: true,
        family: "",
        target: "",
        scriptScoped: false,
        dangerous: false,
        workspace: "",
        runId,
    };
}

beforeEach(() => {
    useApprovalStore.setState({ pending: null, queue: [] });
});

afterEach(() => {
    // The store is process-wide: a leftover dialog would block the composer in
    // every later test file that renders the app.
    useApprovalStore.setState({ pending: null, queue: [] });
});

describe("approval queue", () => {
    test("queues a second request instead of overwriting the first", () => {
        const first = pending("r1", 1);
        const second = pending("r2", 2, "s2");
        useApprovalStore.getState().setPending(first);
        useApprovalStore.getState().setPending(second);

        expect(useApprovalStore.getState().pending?.requestId).toBe("r1");
        expect(useApprovalStore.getState().queue.map((item) => item.requestId))
            .toEqual(["r2"]);
    });

    test("resolving the head promotes the next request", () => {
        useApprovalStore.getState().setPending(pending("r1", 1));
        useApprovalStore.getState().setPending(pending("r2", 2));
        useApprovalStore.getState().resolve("r1");

        expect(useApprovalStore.getState().pending?.requestId).toBe("r2");
        expect(useApprovalStore.getState().queue).toEqual([]);
    });

    test("resolving a queued request leaves the head alone", () => {
        useApprovalStore.getState().setPending(pending("r1", 1));
        useApprovalStore.getState().setPending(pending("r2", 2));
        useApprovalStore.getState().resolve("r2");

        expect(useApprovalStore.getState().pending?.requestId).toBe("r1");
        expect(useApprovalStore.getState().queue).toEqual([]);
    });

    test("clearing a run drops only its entries", () => {
        useApprovalStore.getState().setPending(pending("r1", 1));
        useApprovalStore.getState().setPending(pending("r2", 2));
        useApprovalStore.getState().setPending(pending("r3", 3));
        useApprovalStore.getState().clearRun(2);

        expect(useApprovalStore.getState().pending?.requestId).toBe("r1");
        expect(useApprovalStore.getState().queue.map((item) => item.requestId))
            .toEqual(["r3"]);
    });

    test("the same request id is never queued twice", () => {
        const request = pending("r1", 1);
        useApprovalStore.getState().setPending(request);
        useApprovalStore.getState().setPending(request);
        expect(useApprovalStore.getState().queue).toEqual([]);
    });

    test("closing a session drops its pending and queued requests", () => {
        useApprovalStore.getState().setPending(pending("r1", 1, "s1"));
        useApprovalStore.getState().setPending(pending("r2", 2, "s2"));
        useApprovalStore.getState().setPending(pending("r3", 3, "s1"));
        useApprovalStore.getState().clearSession("s1");

        expect(useApprovalStore.getState().pending?.requestId).toBe("r2");
        expect(useApprovalStore.getState().queue).toEqual([]);
    });

    test("clearing a queued session leaves the head", () => {
        useApprovalStore.getState().setPending(pending("r1", 1, "s1"));
        useApprovalStore.getState().setPending(pending("r2", 2, "s2"));
        useApprovalStore.getState().setPending(pending("r3", 3, "s2"));
        useApprovalStore.getState().clearSession("s2");

        expect(useApprovalStore.getState().pending?.requestId).toBe("r1");
        expect(useApprovalStore.getState().queue).toEqual([]);
    });

    test("recovering prompts drops stale fetched copies only", () => {
        useApprovalStore.getState().setPending(pending("live", 1, "s1"));
        useApprovalStore.getState().setPending(pending("stale", -1, "s1"));
        useApprovalStore.getState().setPending(pending("other", -1, "s2"));

        useApprovalStore.getState().dropFetched("s1", new Set());
        expect(useApprovalStore.getState().pending?.requestId).toBe("live");
        expect(useApprovalStore.getState().queue.map((item) => item.requestId))
            .toEqual(["other"]);

        useApprovalStore.getState().dropFetched("s1", new Set(["other"]));
        expect(useApprovalStore.getState().queue.map((item) => item.requestId))
            .toEqual(["other"]);
    });
});
