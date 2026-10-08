import { beforeEach, describe, expect, it } from "vitest";

import { useApprovalStore, type ApprovalPending } from "./approval-store";

const ghost = (sessionId: string): ApprovalPending => ({
    sessionId,
    requestId: "req-1",
    command: "rm -rf /tmp/x",
    description: "delete",
    toolName: "shell",
    rememberable: true,
    family: "rm *",
});

beforeEach(() => {
    useApprovalStore.setState({ pending: null, pendingBySession: {} });
});

describe("approval pending lifecycle", () => {
    it("surfaces a request for its session", () => {
        const store = useApprovalStore.getState();
        store.setPendingForSession("a", ghost("a"));
        store.setPending(ghost("a"));

        expect(useApprovalStore.getState().pending?.requestId).toBe("req-1");
    });

    it("does not resurrect an answered approval on the single-client return", () => {
        // The reported bug: approve on session A, navigate away, come back, and
        // the dialog reappears (then 404s). Clearing per-session on resolve is
        // what makes syncPendingToSession return nothing on the way back.
        const store = useApprovalStore.getState();
        store.setPendingForSession("a", ghost("a"));
        store.setPending(ghost("a"));

        store.clearPendingForSession("a"); // user answered

        store.syncPendingToSession("b"); // navigate to another thread
        store.syncPendingToSession("a"); // return to A
        expect(useApprovalStore.getState().pending).toBeNull();
    });

    it("keeps other sessions' prompts when one is cleared", () => {
        const store = useApprovalStore.getState();
        store.setPendingForSession("a", ghost("a"));
        store.setPendingForSession("b", ghost("b"));

        store.clearPendingForSession("a");

        store.syncPendingToSession("b");
        expect(useApprovalStore.getState().pending?.sessionId).toBe("b");
        store.syncPendingToSession("a");
        expect(useApprovalStore.getState().pending).toBeNull();
    });
});
