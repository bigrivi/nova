import { describe, expect, test, beforeEach } from "bun:test";
import {
    cycleMode,
    nextMode,
    normalizeMode,
    resetCycleGuard,
    MODE_LABEL,
    MODES,
    usePermissionStore,
} from "./permission-store.ts";

describe("nextMode", () => {
    test("walks the cycle and wraps", () => {
        expect(nextMode("ask")).toBe("acceptEdits");
        expect(nextMode("acceptEdits")).toBe("dontAsk");
        expect(nextMode("dontAsk")).toBe("ask");
    });

    test("every mode in the cycle has a label", () => {
        for (const mode of MODES) {
            expect(MODE_LABEL[mode].length).toBeGreaterThan(0);
        }
    });
});

describe("normalizeMode", () => {
    test("keeps known modes", () => {
        expect(normalizeMode("acceptEdits")).toBe("acceptEdits");
        expect(normalizeMode("dontAsk")).toBe("dontAsk");
        expect(normalizeMode("ask")).toBe("ask");
    });

    test("falls back to ask for anything else", () => {
        expect(normalizeMode(null)).toBe("ask");
        expect(normalizeMode(undefined)).toBe("ask");
        expect(normalizeMode("yolo")).toBe("ask");
    });
});

describe("cycleMode", () => {
    beforeEach(() => {
        usePermissionStore.setState({ mode: "ask" });
        resetCycleGuard();
    });

    test("advances the store once per press", () => {
        cycleMode();
        expect(usePermissionStore.getState().mode).toBe("acceptEdits");
    });

    test("ignores the duplicate event the second listener delivers", () => {
        cycleMode();
        cycleMode();
        expect(usePermissionStore.getState().mode).toBe("acceptEdits");
    });
});
