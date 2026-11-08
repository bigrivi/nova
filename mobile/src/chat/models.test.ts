import { describe, expect, test } from "bun:test";

import type { NovaModelRecord } from "../api/types";
import { groupModelsByProvider, modelPickerSections } from "./models";

function model(
    provider: string,
    id: string,
    providerName = provider,
): NovaModelRecord {
    return {
        id: `${provider}:${id}`,
        provider,
        provider_name: providerName,
        model: id,
        label: id,
        tools: true,
        efforts: [],
    };
}

describe("model grouping", () => {
    test("groups by provider in first-appearance order", () => {
        const groups = groupModelsByProvider([
            model("agnesai", "a1", "Agnes AI"),
            model("opencode", "o1", "OpenCode"),
            model("agnesai", "a2", "Agnes AI"),
        ]);

        expect(groups.map((group) => group.title)).toEqual([
            "Agnes AI",
            "OpenCode",
        ]);
        expect(groups[0]!.models.map((entry) => entry.model)).toEqual([
            "a1",
            "a2",
        ]);
    });

    test("picker sections carry ids and fall back to the model id", () => {
        expect(
            modelPickerSections([
                model("agnesai", "a1", "Agnes AI"),
                model("opencode", "o1", "OpenCode"),
            ]),
        ).toEqual([
            { title: "Agnes AI", items: [{ id: "agnesai:a1", label: "a1" }] },
            { title: "OpenCode", items: [{ id: "opencode:o1", label: "o1" }] },
        ]);
    });

    test("falls back to the provider id when no display name exists", () => {
        expect(groupModelsByProvider([model("p", "m", "")])[0]!.title).toBe(
            "p",
        );
        expect(groupModelsByProvider([])).toEqual([]);
    });
});
