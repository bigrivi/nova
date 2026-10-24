/** Models screen: browse/switch models (persisted to the agent config) */
import { useEffect, useState } from "react";
import type { NovaModelRecord } from "../../api/types.ts";
import { listModels, updateAgent } from "../../api/nova-api.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { SearchableList } from "./SearchableList.tsx";

export function ModelsScreen() {
    const theme = useTheme();
    const [models, setModels] = useState<NovaModelRecord[]>([]);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        void listModels()
            .then((items) => {
                setModels(items);
                setLoaded(true);
            })
            .catch((err: unknown) =>
                setError(err instanceof Error ? err.message : String(err)),
            );
    }, []);

    const currentProvider = useChatStore((s) => s.provider);
    const currentModel = useChatStore((s) => s.model);
    const currentIndex = loaded
        ? Math.max(
              0,
              models.findIndex(
                  (m) => m.provider === currentProvider && m.model === currentModel,
              ),
          )
        : 0;

    async function handleSelect(model: NovaModelRecord): Promise<void> {
        useScreenStore.getState().close();
        useChatStore.setState({
            provider: model.provider,
            model: model.model,
        });
        try {
            await updateAgent("main", {
                provider: model.provider,
                model: model.model,
            });
        } catch {
            // A persistence failure must not block this switch
        }
    }

    if (!loaded) {
        return (
            <box
                position="absolute"
                left="15%"
                right="15%"
                top="15%"
                paddingX={2}
                paddingY={2}
                border
                borderStyle="rounded"
                borderColor={theme.accent}
                backgroundColor={theme.surfaceDeep}
            >
                <text fg={theme.muted}>{error || "Loading..."}</text>
            </box>
        );
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
            initialIndex={currentIndex}
        />
    );
}
