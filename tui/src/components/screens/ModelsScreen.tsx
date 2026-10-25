/** Models screen: browse/switch models (persisted to the agent config) */
import type { NovaModelRecord } from "../../api/types.ts";
import { listModels, updateAgent } from "../../api/nova-api.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { SearchableList } from "./SearchableList.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { useListScreen } from "./use-list-screen.ts";

export function ModelsScreen() {
    const currentProvider = useChatStore((state) => state.provider);
    const currentModel = useChatStore((state) => state.model);
    const { items: models, ready, error, initialIndex } = useListScreen(
        listModels,
        (items) =>
            items.findIndex(
                (model) =>
                    model.provider === currentProvider &&
                    model.model === currentModel,
            ),
    );

    async function handleSelect(model: NovaModelRecord): Promise<void> {
        useScreenStore.getState().close();
        const nextEffort =
            model.efforts.length > 0 ? model.efforts[0] : "";
        useChatStore.setState({
            provider: model.provider,
            model: model.model,
            reasoningEffort: nextEffort,
        });
        try {
            await updateAgent("main", {
                provider: model.provider,
                model: model.model,
                reasoning_effort: nextEffort || null,
            });
        } catch {
            // A persistence failure must not block this switch
        }
    }

    if (!ready) {
        return <ScreenLoading message={error || "Loading models..."} />;
    }

    return (
        <SearchableList
            title="Models"
            items={models}
            filter={(model, query) =>
                !query ||
                model.label.toLowerCase().includes(query.toLowerCase()) ||
                model.provider.includes(query) ||
                model.model.includes(query)
            }
            renderLabel={(model) => `${model.provider_name} / ${model.label}`}
            onSelect={(model) => void handleSelect(model)}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no models configured"}
            initialIndex={initialIndex}
        />
    );
}
