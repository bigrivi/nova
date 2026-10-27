/** Variants screen: browse/switch reasoning effort levels for the active model */
import { listModels, updateAgent } from "../../api/nova-api.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { SearchableList } from "./SearchableList.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { useListScreen } from "./use-list-screen.ts";

export function VariantsScreen() {
    const provider = useChatStore((s) => s.provider);
    const model = useChatStore((s) => s.model);
    const currentEffort = useChatStore((s) => s.reasoningEffort);

    const { items: models, ready, error } = useListScreen(listModels);

    const levels =
        models.find((m) => m.provider === provider && m.model === model)
            ?.efforts ?? [];

    if (!ready) {
        return <ScreenLoading message={error || "Loading variants..."} />;
    }

    if (levels.length === 0) {
        return (
            <ScreenLoading
                message={
                    error ||
                    "this model has no reasoning effort levels configured"
                }
            />
        );
    }

    async function handleSelect(value: string): Promise<void> {
        useScreenStore.getState().close();
        useChatStore.setState({ reasoningEffort: value });
        try {
            await updateAgent("main", {
                provider,
                model,
                reasoning_effort: value,
            });
        } catch {
            // persistence failure must not block the switch
        }
    }

    return (
        <SearchableList
            title="Variants"
            items={levels.map((level) => ({ label: level, value: level }))}
            defaultValue={currentEffort}
            onSelect={(value) => void handleSelect(value)}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no variants"}
        />
    );
}
