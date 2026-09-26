import { beforeEach, describe, expect, it } from "vitest";

import { useReasoningStore } from "./reasoning-store";

beforeEach(() => {
    useReasoningStore.setState({ compacting: false, compactionSummary: "" });
});

describe("compaction summary", () => {
    it("appends streamed chunks in order", () => {
        const store = useReasoningStore.getState();
        store.setCompacting(true);
        store.appendCompactionDelta("Request: ");
        store.appendCompactionDelta("fix it");

        expect(useReasoningStore.getState().compactionSummary).toBe(
            "Request: fix it",
        );
    });

    it("clears the previous run when a new compaction starts", () => {
        const store = useReasoningStore.getState();
        store.setCompacting(true);
        store.appendCompactionDelta("stale text");
        store.setCompacting(false);
        store.setCompacting(true);

        expect(useReasoningStore.getState().compactionSummary).toBe("");
    });

    it("keeps the text when compaction finishes", () => {
        const store = useReasoningStore.getState();
        store.setCompacting(true);
        store.appendCompactionDelta("folded history");
        store.setCompacting(false);

        expect(useReasoningStore.getState().compacting).toBe(false);
        expect(useReasoningStore.getState().compactionSummary).toBe(
            "folded history",
        );
    });
});
