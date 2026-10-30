/** Models screen: browse/switch models (persisted to the agent config) */
import { listModels, updateAgent } from "../../api/nova-api.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { SearchableList } from "./SearchableList.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { useListScreen } from "./use-list-screen.ts";

export function ModelsScreen() {
    const currentProvider = useChatStore((state) => state.provider);
    const currentModel = useChatStore((state) => state.model);
    const { items: models, ready, error, defaultValue } = useListScreen(
        listModels,
        (items) =>
            items.find(
                (m) =>
                    m.provider === currentProvider &&
                    m.model === currentModel,
            )?.id,
    );

    async function handleSelect(value: string): Promise<void> {
        const model = models.find((m) => m.id === value);
        if (!model) return;
        useScreenStore.getState().close();
        const nextEffort =
            model.efforts.length > 0 ? model.efforts[0] : "";
        useChatStore.setState({
            provider: model.provider,
            model: model.model,
            reasoningEffort: nextEffort,
        });
        try {
            // The picker sets the default for the agent this conversation
            // belongs to; a hardcoded key silently edited someone else's row.
            await updateAgent(useChatStore.getState().agentKey || "main", {
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
            items={models.map((model) => ({
                label: model.label,
                value: model.id,
                group: model.provider_name,
                provider: model.provider,
                modelId: model.model,
            }))}
            filter={(item, query) => {
                const needle = query.toLowerCase();
                return (
                    item.label.toLowerCase().includes(needle) ||
                    item.provider.includes(needle) ||
                    item.modelId.includes(needle)
                );
            }}
            onSelect={(value) => void handleSelect(value)}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no models configured"}
            defaultValue={defaultValue}
        />
    );
}
