import { startTransition, useMemo, useState } from "react";

import type { ModelOption } from "../../components/assistant-ui/elements/model-selector";
import { listProviders, updateAgent } from "../../lib/nova-api";
import type { NovaModelRecord, NovaProviderRecord } from "../../types/nova";

export interface ModelConfig {
    models: NovaModelRecord[];
    setModels: React.Dispatch<React.SetStateAction<NovaModelRecord[]>>;
    /**
     * The same models in the selector's shape, carrying the effort levels the
     * server resolved. Built here so the effort filter and the picker cannot
     * disagree about what a model supports.
     */
    modelOptions: ModelOption[];
    providers: NovaProviderRecord[];
    setProviders: React.Dispatch<React.SetStateAction<NovaProviderRecord[]>>;
    selectedModelId: string | null;
    setSelectedModelId: React.Dispatch<React.SetStateAction<string | null>>;
    handleModelSelect: (value: string) => void;
    handleConfigModelsUpdated: (nextModels: NovaModelRecord[]) => void;
    refreshProviders: () => Promise<void>;
    handleConfigStatus: (message: string | null) => void;
}

/**
 * Own the model/provider catalog and the active model selection. Selecting a
 * model (or falling back after a catalog change) persists it onto the main
 * agent so the choice survives reloads.
 */
export function useModelConfig(): ModelConfig {
    const [models, setModels] = useState<NovaModelRecord[]>([]);
    const [providers, setProviders] = useState<NovaProviderRecord[]>([]);
    const [selectedModelId, setSelectedModelId] = useState<string | null>(null);

    const modelOptions = useMemo<ModelOption[]>(
        () =>
            models.map((model) => ({
                id: model.id,
                name: model.label,
                keywords: [
                    model.label,
                    model.provider_name,
                    model.provider,
                    model.id,
                ],
                // An empty list keeps the effort control out of the picker.
                // Levels keep the provider's own spelling: they are the values
                // that go on the wire and appear in the provider's docs, so
                // translating them would make the UI disagree with both.
                efforts:
                    model.efforts.length > 0
                        ? model.efforts.map((id) => ({ id, name: id }))
                        : undefined,
            })),
        [models],
    );

    function handleModelSelect(value: string) {
        setSelectedModelId(value);
        const [provider, model] = value.split(":");
        if (provider && model) {
            updateAgent("main", { provider, model }).catch(() => {});
        }
    }

    function handleConfigModelsUpdated(nextModels: NovaModelRecord[]) {
        startTransition(() => {
            setModels(nextModels);
            if (
                selectedModelId &&
                nextModels.some((model) => model.id === selectedModelId)
            ) {
                return;
            }
            const fallback = nextModels[0] ?? null;
            setSelectedModelId(fallback?.id ?? null);
            if (fallback?.provider && fallback?.model) {
                updateAgent("main", {
                    provider: fallback.provider,
                    model: fallback.model,
                }).catch(() => {});
            }
        });
    }

    async function refreshProviders() {
        const nextProviders = await listProviders();
        startTransition(() => {
            setProviders(nextProviders);
        });
    }

    function handleConfigStatus(message: string | null) {
        console.debug(message);
    }

    return {
        models,
        setModels,
        modelOptions,
        providers,
        setProviders,
        selectedModelId,
        setSelectedModelId,
        handleModelSelect,
        handleConfigModelsUpdated,
        refreshProviders,
        handleConfigStatus,
    };
}
