/** Variants screen: browse/switch reasoning effort levels for the active model */
import { useEffect, useState } from "react";
import { listModels, updateAgent } from "../../api/nova-api.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";

export function VariantsScreen() {
    const theme = useTheme();
    const provider = useChatStore((s) => s.provider);
    const model = useChatStore((s) => s.model);
    const currentEffort = useChatStore((s) => s.reasoningEffort);

    const [levels, setLevels] = useState<string[]>([]);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        let cancelled = false;
        void listModels()
            .then((items) => {
                if (cancelled) return;
                const match = items.find(
                    (m) => m.provider === provider && m.model === model,
                );
                setLevels(match?.efforts ?? []);
                setLoaded(true);
            })
            .catch((err: unknown) => {
                if (cancelled) return;
                setError(err instanceof Error ? err.message : String(err));
                setLoaded(true);
            });
        return () => {
            cancelled = true;
        };
    }, [provider, model]);

    if (!loaded) {
        return <ScreenLoading message={error || "Loading variants..."} />;
    }

    if (levels.length === 0) {
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
                <text fg={theme.muted}>
                    this model has no reasoning effort levels configured
                </text>
            </box>
        );
    }

    const currentIndex = Math.max(0, levels.indexOf(currentEffort));

    async function handleSelect(level: string): Promise<void> {
        useScreenStore.getState().close();
        useChatStore.setState({ reasoningEffort: level });
        try {
            await updateAgent("main", {
                provider,
                model,
                reasoning_effort: level,
            });
        } catch {
            // persistence failure must not block the switch
        }
    }

    return (
        <SearchableList
            title="Variants"
            items={levels}
            filter={(level, query) =>
                !query || level.toLowerCase().includes(query.toLowerCase())
            }
            renderLabel={(level) =>
                level === currentEffort ? `${level}  (current)` : level
            }
            onSelect={(level) => void handleSelect(level)}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no variants"}
            initialIndex={currentIndex}
        />
    );
}
