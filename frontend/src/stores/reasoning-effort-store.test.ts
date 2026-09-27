import { beforeEach, describe, expect, it } from "vitest";

import {
    effortRatio,
    effortRungAt,
    trackWidth,
} from "../components/assistant-ui/elements/reasoning-effort";
import {
    resolveModelEffort,
    type ModelOption,
} from "../components/assistant-ui/elements/model-selector";
import { useReasoningEffortStore } from "./reasoning-effort-store";

const LADDER = ["minimal", "low", "medium", "high", "xhigh"];

function option(
    id: string,
    efforts: string[] | undefined,
): ModelOption {
    return {
        id,
        name: id,
        ...(efforts && efforts.length > 0
            ? { efforts: efforts.map((level) => ({ id: level, name: level })) }
            : {}),
    };
}

const MODELS: ModelOption[] = [
    option("gw:gpt-5.5", LADDER),
    // Declares nothing, so it offers no control.
    option("gw:plain-model", undefined),
    // A gateway serving a different, shorter ladder.
    option("gw:mimo-v2.5", ["low", "high"]),
];

beforeEach(() => {
    useReasoningEffortStore.setState({ effort: null });
});

describe("reasoning level selection", () => {
    it("resolves a level the selected model declares", () => {
        expect(
            resolveModelEffort(MODELS, "gw:gpt-5.5", "xhigh"),
        ).toBe("xhigh");
    });

    it("offers nothing for a model that declares nothing", () => {
        expect(resolveModelEffort(MODELS, "gw:plain-model", "high")).toBe(
            undefined,
        );
    });

    it("drops a level the selected model does not declare", () => {
        // "xhigh" belongs to gpt-5.5; mimo-v2.5 never offered it.
        expect(resolveModelEffort(MODELS, "gw:mimo-v2.5", "xhigh")).toBe(
            undefined,
        );
        expect(resolveModelEffort(MODELS, "gw:mimo-v2.5", "low")).toBe("low");
    });

    it("resolves nothing for an unknown or unselected model", () => {
        expect(resolveModelEffort(MODELS, undefined, "high")).toBe(undefined);
        expect(resolveModelEffort(MODELS, "gw:gone", "high")).toBe(undefined);
    });

    it("resolves nothing when no level was chosen", () => {
        expect(resolveModelEffort(MODELS, "gw:gpt-5.5", undefined)).toBe(
            undefined,
        );
    });

    it("keeps the choice when the model is switched away and back", () => {
        // The store holds the raw choice so returning to a model restores the
        // level that was picked for it, rather than leaving nothing selected.
        useReasoningEffortStore.getState().setEffort("xhigh");

        const away = resolveModelEffort(
            MODELS,
            "gw:mimo-v2.5",
            useReasoningEffortStore.getState().effort ?? undefined,
        );
        const back = resolveModelEffort(
            MODELS,
            "gw:gpt-5.5",
            useReasoningEffortStore.getState().effort ?? undefined,
        );

        expect(away).toBe(undefined);
        expect(back).toBe("xhigh");
        expect(useReasoningEffortStore.getState().effort).toBe("xhigh");
    });

    it("does not filter on write", () => {
        // Filtering here would discard the level for every other model, so the
        // store stays a record of intent and resolution happens at render.
        useReasoningEffortStore.getState().setEffort("xhigh");
        expect(useReasoningEffortStore.getState().effort).toBe("xhigh");
    });
});

describe("slider geometry", () => {
    it("spreads the rungs across the whole track", () => {
        // With no captions to line up with, the rungs run end to end and the
        // rail needs no inset of its own.
        for (const count of [2, 3, 4, 5, 6]) {
            expect(effortRatio(0, count)).toBe(0);
            expect(effortRatio(count - 1, count)).toBe(1);
        }
    });

    it("spaces the rungs evenly", () => {
        expect(effortRatio(2, 5)).toBe(0.5);
        expect(effortRatio(0, 4)).toBe(0);
        expect(effortRatio(3, 4)).toBe(1);
        expect(effortRatio(1, 3)).toBeCloseTo(0.5);
    });

    it("collapses a single rung to the start", () => {
        // One rung is rendered as a readout, not a slider, so the ratio is only
        // ever a fallback; 0 keeps the fill from covering the whole rail.
        expect(effortRatio(0, 1)).toBe(0);
        expect(effortRatio(0, 0)).toBe(0);
    });

    it("rounds a drop to the nearest rung", () => {
        expect(effortRungAt(0, 5)).toBe(0);
        expect(effortRungAt(0.5, 5)).toBe(2);
        expect(effortRungAt(1, 5)).toBe(4);
        expect(effortRungAt(0.26, 5)).toBe(1);
    });

    it("clamps a drag released past either end", () => {
        // Wrapping instead would send "the most" back to the least.
        expect(effortRungAt(-0.4, 5)).toBe(0);
        expect(effortRungAt(1.9, 5)).toBe(4);
    });

    it("treats a degenerate measurement as the first rung", () => {
        expect(effortRungAt(Number.NaN, 5)).toBe(0);
        expect(effortRungAt(0.5, 1)).toBe(0);
        expect(effortRungAt(0.5, 0)).toBe(0);
    });

    it("widens the track as rungs are added", () => {
        const widths = [1, 2, 3, 4, 5, 6].map(trackWidth);
        expect(widths).toEqual([...widths].sort((a, b) => a - b));
    });
});
