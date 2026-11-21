import { expect, mock, test } from "bun:test";

import type { NovaStats } from "../api/types.ts";

type Resolver = (value: NovaStats) => void;

let calls: string[] = [];
let impl: (sessionId?: string | null) => Promise<NovaStats> = () =>
    Promise.resolve(stats(0));

mock.module("../api/stats.ts", () => ({
    fetchStats: (sessionId?: string | null) => {
        calls.push(sessionId ?? "");
        return impl(sessionId);
    },
}));

const { refreshSessionStats } = await import("./session-usage.ts");
const { useUsageStore } = await import("../stores/usage-store.ts");

function stats(cost: number): NovaStats {
    return {
        scope: "session",
        days: null,
        since: null,
        tokens: { input: 0, output: 0, cache_read: 0, total: 0 },
        cost: { total: cost, priced: true, unpriced_models: 0 },
        messages: 1,
        by_model: [],
        session: { turns: 1, messages: 1, started_at: 0, updated_at: 0 },
    };
}

function deferred(): { promise: Promise<NovaStats>; resolve: Resolver } {
    let resolve: Resolver = () => {};
    const promise = new Promise<NovaStats>((done) => {
        resolve = done;
    });
    return { promise, resolve };
}

async function flush(): Promise<void> {
    await new Promise((done) => setTimeout(done, 0));
}

test("writes the read into the session's bucket", async () => {
    calls = [];
    impl = () => Promise.resolve(stats(2));

    refreshSessionStats("s-write");
    await flush();

    expect(calls).toEqual(["s-write"]);
    expect(useUsageStore.getState().byId["s-write"]?.cost.total).toBe(2);
});

test("concurrent reads for one session share a request", async () => {
    calls = [];
    const pending = deferred();
    impl = () => pending.promise;

    refreshSessionStats("s-dedupe");
    refreshSessionStats("s-dedupe");
    expect(calls).toEqual(["s-dedupe"]);

    pending.resolve(stats(1));
    await flush();
});

test("a read requested mid-flight runs once more when it lands", async () => {
    calls = [];
    const pending: Resolver[] = [];
    impl = () =>
        new Promise<NovaStats>((resolve) => {
            pending.push(resolve);
        });

    refreshSessionStats("s-rerun");
    refreshSessionStats("s-rerun");
    expect(calls).toEqual(["s-rerun"]);

    pending[0]?.(stats(1));
    await flush();
    expect(calls).toEqual(["s-rerun", "s-rerun"]);

    pending[1]?.(stats(2));
    await flush();
    expect(useUsageStore.getState().byId["s-rerun"]?.cost.total).toBe(2);
});
