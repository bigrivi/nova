/** Provider grouping for the model picker, matching the web selector. */
import type { NovaModelRecord } from "../api/types";

export type ModelGroup = {
    provider: string;
    title: string;
    models: NovaModelRecord[];
};

/**
 * Group models by provider, keeping the server's order inside each group.
 *
 * @param models Models in the order the server listed them.
 * @returns One group per provider, in first-appearance order.
 */
export type ModelPickerSection = {
    title: string;
    items: Array<{ id: string; label: string }>;
};

/** Picker rows: one section per provider, labels falling back to the model id. */
export function modelPickerSections(
    models: readonly NovaModelRecord[],
): ModelPickerSection[] {
    return groupModelsByProvider(models).map((group) => ({
        title: group.title,
        items: group.models.map((model) => ({
            id: model.id,
            label: model.label || model.model,
        })),
    }));
}

export function groupModelsByProvider(
    models: readonly NovaModelRecord[],
): ModelGroup[] {
    const groups = new Map<string, ModelGroup>();
    for (const model of models) {
        const existing = groups.get(model.provider);
        if (existing) {
            existing.models.push(model);
            continue;
        }
        groups.set(model.provider, {
            provider: model.provider,
            title: model.provider_name || model.provider,
            models: [model],
        });
    }
    return [...groups.values()];
}
