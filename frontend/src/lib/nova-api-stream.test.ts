import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    clearLastSequence,
    getLastSequence,
    setLastSequence,
    streamBackoffBaseMs,
    streamChat,
} from "./nova-api";

function installMemoryStorage() {
    const store = new Map<string, string>();
    (globalThis as Record<string, unknown>).localStorage = {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => {
            store.set(key, value);
        },
        removeItem: (key: string) => {
            store.delete(key);
        },
    };
}

describe("streamBackoffBaseMs", () => {
    it("backs off exponentially from 1s and caps at 30s", () => {
        expect(streamBackoffBaseMs(0)).toBe(1000);
        expect(streamBackoffBaseMs(1)).toBe(2000);
        expect(streamBackoffBaseMs(2)).toBe(4000);
        expect(streamBackoffBaseMs(10)).toBe(30000);
        expect(streamBackoffBaseMs(-1)).toBe(1000);
    });
});

describe("lastSequence localStorage", () => {
    beforeEach(() => {
        installMemoryStorage();
    });

    it("persists the resume cursor per session", () => {
        expect(getLastSequence("sess-a")).toBeNull();
        setLastSequence("sess-a", 7);
        setLastSequence("sess-b", 3);
        expect(getLastSequence("sess-a")).toBe(7);
        expect(getLastSequence("sess-b")).toBe(3);
    });

    it("clears the cursor when a turn completes", () => {
        setLastSequence("sess-a", 7);
        clearLastSequence("sess-a");
        expect(getLastSequence("sess-a")).toBeNull();
    });

    it("rejects corrupt stored values", () => {
        const storage = (
            globalThis as unknown as {
                localStorage: { setItem: (k: string, v: string) => void };
            }
        ).localStorage;
        storage.setItem("nova:lastSeq:sess-c", "not-a-number");
        expect(getLastSequence("sess-c")).toBeNull();
        storage.setItem("nova:lastSeq:sess-c", "-4");
        expect(getLastSequence("sess-c")).toBeNull();
    });
});

describe("streamChat retry", () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    function sseResponse(frames: string[], error?: unknown): Response {
        const encoder = new TextEncoder();
        const chunks = frames.map((frame) => encoder.encode(frame));
        let index = 0;
        const body = {
            getReader() {
                return {
                    async read() {
                        if (index < chunks.length) {
                            return { done: false as const, value: chunks[index++] };
                        }
                        if (error) {
                            throw error;
                        }
                        return { done: true as const, value: undefined };
                    },
                };
            },
        };
        return { ok: true, status: 200, text: async () => "", body } as unknown as Response;
    }

    function requestBodies(fetchMock: ReturnType<typeof vi.fn>) {
        return fetchMock.mock.calls.map((call) =>
            JSON.parse(String((call[1] as RequestInit)?.body)),
        );
    }

    it("fails loudly instead of retrying when no session was announced", async () => {
        // Re-posting a pre-session turn could clone it server-side (the
        // original may still be alive without an id we could resume).
        const fetchMock = vi.fn(async () => new Response("boom", { status: 500 }));
        vi.stubGlobal("fetch", fetchMock);

        await expect(streamChat({ message: "hi", onEvent: () => {} })).rejects.toThrow();
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("retries with the learned session id instead of cloning the turn", async () => {
        const fetchMock = vi.fn(async () => {
            if (fetchMock.mock.calls.length === 1) {
                return sseResponse(
                    [
                        'id: 1\ndata: {"type":"data-nova-session","data":{"sessionId":"sess-x"}}\n\n',
                    ],
                    new Error("mid-stream break"),
                );
            }
            return sseResponse(["data: [DONE]\n\n"]);
        });
        vi.stubGlobal("fetch", fetchMock);

        await streamChat({ message: "hi", onEvent: () => {} });

        expect(fetchMock).toHaveBeenCalledTimes(2);
        const bodies = requestBodies(fetchMock);
        expect(bodies[0]).toMatchObject({ message: "hi" });
        expect(bodies[0]).not.toHaveProperty("session_id");
        expect(bodies[1]).toMatchObject({ session_id: "sess-x", resume_from_seq: 1 });
    });
});
