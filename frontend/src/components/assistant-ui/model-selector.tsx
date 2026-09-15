import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
    ModelSelectorContent,
    ModelSelectorEmpty,
    ModelSelectorGroup,
    ModelSelectorItem,
    ModelSelectorList,
    ModelSelectorRoot,
    ModelSelectorSearch,
    ModelSelectorSeparator,
    ModelSelectorTrigger,
    ModelSelectorValue,
    type ModelOption,
} from "./elements/model-selector";

import type { NovaModelRecord } from "../../types/nova";

type ModelSelectorProps = {
    models: NovaModelRecord[];
    selectedModelId: string | null;
    onSelect: (modelId: string) => void;
};

type ModelGroup = {
    provider: string;
    providerName: string;
    models: NovaModelRecord[];
};

function groupModels(models: NovaModelRecord[]): ModelGroup[] {
    const groups = new Map<string, ModelGroup>();

    for (const model of models) {
        const existing = groups.get(model.provider);
        if (existing) {
            existing.models.push(model);
            continue;
        }

        groups.set(model.provider, {
            provider: model.provider,
            providerName: model.provider_name,
            models: [model],
        });
    }

    return [...groups.values()];
}

export function ModelSelector({
    models,
    selectedModelId,
    onSelect,
}: ModelSelectorProps) {
    const { t } = useTranslation();
    const selectId = "nova-model-select";
    const groupedModels = useMemo(() => groupModels(models), [models]);
    const selectedModel = models.find((model) => model.id === selectedModelId);
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
            })),
        [models],
    );

    function toModelOption(model: NovaModelRecord): ModelOption {
        return (
            modelOptions.find((option) => option.id === model.id) ?? {
                id: model.id,
                name: model.label,
            }
        );
    }

    return (
        <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor={selectId}>
                {t("modelSelector.activeModel")}
            </label>
            <ModelSelectorRoot
                models={modelOptions}
                value={selectedModelId ?? undefined}
                onValueChange={onSelect}
            >
                <ModelSelectorTrigger
                    id={selectId}
                    aria-label={t("modelSelector.activeModel")}
                    title={
                        selectedModel?.label ||
                        t("modelSelector.noModelsAvailable")
                    }
                    size="sm"
                    className="h-8 w-auto max-w-[240px] rounded-full border-border/60 bg-background/85 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/35 hover:text-muted-foreground focus:bg-background focus:text-foreground"
                >
                    <ModelSelectorValue
                        placeholder={t("modelSelector.noModelsAvailable")}
                        showEffort={false}
                    />
                </ModelSelectorTrigger>
                <ModelSelectorContent
                    align="end"
                    searchable
                    className="max-w-[calc(100vw-2rem)]"
                >
                    <ModelSelectorSearch
                        placeholder={t("modelSelector.searchModels")}
                    />
                    <ModelSelectorList>
                        <ModelSelectorEmpty>
                            {t("modelSelector.noMatchingModels")}
                        </ModelSelectorEmpty>
                        {groupedModels.flatMap((group, index) => {
                            const parts = [
                                <ModelSelectorGroup
                                    key={group.provider}
                                    heading={group.providerName}
                                >
                                    {group.models.map((model) => (
                                        <ModelSelectorItem
                                            key={model.id}
                                            model={toModelOption(model)}
                                        />
                                    ))}
                                </ModelSelectorGroup>,
                            ];
                            if (index < groupedModels.length - 1) {
                                parts.push(
                                    <ModelSelectorSeparator
                                        key={`${group.provider}-separator`}
                                    />,
                                );
                            }
                            return parts;
                        })}
                    </ModelSelectorList>
                </ModelSelectorContent>
            </ModelSelectorRoot>
        </div>
    );
}
