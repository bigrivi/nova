/** Rewind screen: pick a turn that changed files and undo it */
import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import {
    listCheckpoints,
    listMessages,
    restoreCheckpoint,
} from "../../api/nova-api.ts";
import type { NovaCheckpoint } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { recordsToMessages } from "../../utils/history.ts";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { useListScreen } from "./use-list-screen.ts";

const MAX_ROWS = 40;

export function relativeAge(createdAt: number): string {
    const seconds = Math.max(0, Math.round((Date.now() - createdAt) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
    return `${Math.round(seconds / 3600)}h ago`;
}

export function RewindScreen() {
    const theme = useTheme();
    const sessionId = useChatStore((state) => state.sessionId);
    const [confirming, setConfirming] = useState<NovaCheckpoint | null>(null);

    const { items, ready, error } = useListScreen(() =>
        sessionId ? listCheckpoints(sessionId) : Promise.resolve([]),
    );

    useKeyboard((key) => {
        if (!confirming) return;
        if (key.name === "y") {
            void apply(confirming);
        } else if (key.name === "n" || key.name === "escape") {
            setConfirming(null);
        }
    });

    async function apply(checkpoint: NovaCheckpoint): Promise<void> {
        if (!sessionId) return;
        setConfirming(null);
        try {
            const report = await restoreCheckpoint(sessionId, checkpoint.checkpoint_id);
            useScreenStore.getState().close();
            // The turns after the checkpoint no longer exist, so the transcript
            // has to come from the backend rather than be patched in place.
            const records = await listMessages(sessionId);
            useChatStore
                .getState()
                .loadHistory(sessionId, recordsToMessages(records));
            const skipped = report.skipped.length;
            useToastStore
                .getState()
                .show(
                    `Rewound ${report.restored.length + report.deleted.length} file(s), dropped ${report.dropped_messages} message(s)` +
                        (skipped ? `, ${skipped} skipped` : ""),
                    5000,
                );
        } catch (err) {
            useToastStore
                .getState()
                .show(
                    `Rewind failed: ${err instanceof Error ? err.message : String(err)}`,
                    5000,
                );
        }
    }

    if (!ready) {
        return <ScreenLoading message={error || "Loading rewind points..."} />;
    }

    if (confirming) {
        const files = confirming.files;
        return (
            <ScreenPanel width="60%">
                <box flexDirection="column" gap={1}>
                    <text fg={theme.text.base} content="Rewind to this point?" />
                    <text
                        fg={theme.text.muted}
                        content={`${files} file(s) will be restored and the messages from this turn on will be dropped.`}
                    />
                    <text
                        fg={theme.text.faint}
                        content="y confirm · n cancel (files changed since the agent wrote them are skipped)"
                    />
                </box>
            </ScreenPanel>
        );
    }

    if (items.length === 0) {
        return (
            <ScreenLoading
                message={error || "No rewind points: no turn changed a file"}
            />
        );
    }

    return (
        <SearchableList
            title="Rewind"
            items={items.slice(0, MAX_ROWS).map((item) => ({
                label: `${item.label || "(untitled)"} · ${item.files} file(s) · ${relativeAge(item.created_at)}`,
                value: item.checkpoint_id,
            }))}
            onSelect={(value) => {
                const item = items.find((entry) => entry.checkpoint_id === value);
                if (item) setConfirming(item);
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no rewind points"}
        />
    );
}
