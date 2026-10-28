import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { useChatStore } from "../stores/chat-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import {
    requestInterrupt,
    resetInterruptGuardForTest,
} from "./chat-stream.ts";

const originalFetch = globalThis.fetch;
let calls = 0;

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

beforeEach(() => {
    calls = 0;
    resetInterruptGuardForTest();
    useToastStore.setState({ message: null });
});

afterEach(() => {
    globalThis.fetch = originalFetch;
    useChatStore.setState({ sessionId: null, isStreaming: false });
});

function stubFetch(handler: () => Response): void {
    globalThis.fetch = (() => {
        calls += 1;
        return Promise.resolve(handler());
    }) as unknown as typeof fetch;
}

function streamingAs(sessionId: string): void {
    useChatStore.setState({ sessionId, isStreaming: true });
}

describe("requestInterrupt", () => {
    test("two immediate calls produce one fetch", async () => {
        streamingAs("s1");
        stubFetch(() => jsonResponse({ session_id: "s1", interrupted: true }));
        await Promise.all([requestInterrupt(), requestInterrupt()]);
        expect(calls).toBe(1);
    });

    test("no-op when not streaming", async () => {
        stubFetch(() => jsonResponse({ session_id: "s1", interrupted: true }));
        await requestInterrupt();
        expect(calls).toBe(0);
    });

    test("false outcome toasts nothing-to-cancel", async () => {
        streamingAs("s1");
        stubFetch(() => jsonResponse({ session_id: "s1", interrupted: false }));
        await requestInterrupt();
        expect(calls).toBe(1);
        expect(useToastStore.getState().message).toContain("already ended");
    });

    test("null outcome toasts unreachable", async () => {
        streamingAs("s1");
        stubFetch(() => new Response("err", { status: 500 }));
        await requestInterrupt();
        expect(useToastStore.getState().message).toContain("Could not reach");
    });

    test("true outcome shows no toast", async () => {
        streamingAs("s1");
        stubFetch(() => jsonResponse({ session_id: "s1", interrupted: true }));
        await requestInterrupt();
        expect(useToastStore.getState().message).toBeNull();
    });
});
