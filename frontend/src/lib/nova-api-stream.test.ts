import { beforeEach, describe, expect, it } from "vitest";

import {
    clearLastSequence,
    getLastSequence,
    setLastSequence,
    streamBackoffBaseMs,
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
