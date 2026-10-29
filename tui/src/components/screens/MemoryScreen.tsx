/** Memory panel: what the agent stored, grouped by scope, with delete */
import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import { deleteMemory, listMemories } from "../../api/memory.ts";
import type { NovaMemory } from "../../api/types.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { arrangeMemories, memoryDetailLines } from "../../lib/memory-format.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { useListScreen } from "./use-list-screen.ts";

export function MemoryScreen() {
    const [selected, setSelected] = useState<NovaMemory | null>(null);
    const [confirming, setConfirming] = useState(false);
    const { items, ready, error, reload } = useListScreen(() => listMemories());

    useKeyboard((key) => {
        if (!selected) return;
        if (key.name === "escape" || key.name === "q") {
            if (confirming) {
                setConfirming(false);
            } else {
                setSelected(null);
            }
            return;
        }
        if (key.name === "d") {
            setConfirming(true);
            return;
        }
        if (key.name === "y" && confirming) {
            void remove(selected);
        }
    });

    async function remove(memory: NovaMemory): Promise<void> {
        setConfirming(false);
        try {
            await deleteMemory(memory.id);
            setSelected(null);
            reload();
            useToastStore.getState().show("Memory deleted", 3000);
        } catch (err) {
            useToastStore
                .getState()
                .show(
                    `Delete failed: ${err instanceof Error ? err.message : String(err)}`,
                    4000,
                );
        }
    }

    if (!ready) {
        return <ScreenLoading message={error || "Loading memories..."} />;
    }

    if (selected) {
        return (
            <MemoryDetail memory={selected} confirming={confirming} />
        );
    }

    const rows = arrangeMemories(items);

    return (
        <SearchableList
            title="Memories"
            items={rows.map((row) => ({
                label: row.label,
                value: row.id,
                group: row.group,
            }))}
            onSelect={(value) => {
                const memory = items.find((entry) => entry.id === value);
                if (memory) setSelected(memory);
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no memories stored yet"}
        />
    );
}

function MemoryDetail({
    memory,
    confirming,
}: {
    memory: NovaMemory;
    confirming: boolean;
}) {
    const theme = useTheme();
    return (
        <ScreenPanel width="75%">
            <box flexDirection="column" gap={1}>
                {memoryDetailLines(memory).map((line, index) => (
                    <text
                        key={`${index}-${line.slice(0, 12)}`}
                        fg={index === 0 ? theme.text.muted : theme.text.base}
                        content={line}
                    />
                ))}
                <text
                    fg={confirming ? theme.feedback.error : theme.text.faint}
                    content={
                        confirming
                            ? "delete this memory? y confirm · esc cancel"
                            : "d delete · esc back"
                    }
                />
            </box>
        </ScreenPanel>
    );
}
