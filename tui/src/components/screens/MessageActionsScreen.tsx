/** Click a user message → a small menu of what you can do with it. */
import { useKeyboard } from "@opentui/react";
import { useRenderer } from "@opentui/react";
import { useEffect, useState } from "react";
import {
    listCheckpoints,
    restoreCheckpoint,
} from "../../api/nova-api.ts";
import { forkSession } from "../../api/session-actions.ts";
import { openSession } from "../../lib/open-session.ts";
import { extractCodeBlocks } from "../../lib/code-blocks.ts";
import type { NovaCheckpoint } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useEditStore } from "../../stores/edit-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { recordsToMessages } from "../../utils/history.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { SearchableList } from "./SearchableList.tsx";

type Action = {
    label: string;
    value: "edit" | "copy" | "copy-code" | "rewind" | "fork";
};

export function MessageActionsScreen({
    messageId,
    text,
}: {
    messageId: string;
    text: string;
}) {
    const theme = useTheme();
    const renderer = useRenderer();
    const sessionId = useChatStore((state) => state.sessionId);
    const [confirming, setConfirming] = useState<NovaCheckpoint | null>(null);
    const [ready, setReady] = useState(true);
    const [hasCheckpoint, setHasCheckpoint] = useState<boolean | null>(null);

    // Whether this message has a checkpoint is only known after asking. We ask
    // lazily: the menu opens with "Edit" and "Copy" (always available) and
    // gains "Rewind" once the checkpoint is confirmed to exist.
    useEffect(() => {
        if (!sessionId) return;
        let cancelled = false;
        void (async () => {
            try {
                const items = await listCheckpoints(sessionId);
                if (cancelled) return;
                setHasCheckpoint(items.some((item) => item.checkpoint_id === messageId));
            } catch {
                if (cancelled) return;
                setHasCheckpoint(false);
            }
            setReady(true);
        })();
        return () => {
            cancelled = true;
        };
    }, [sessionId, messageId]);

    const codeBlocks = extractCodeBlocks(text);
    const actions: Action[] = [
        { label: "Edit this question", value: "edit" },
        { label: "Copy text", value: "copy" },
        { label: "Fork from here", value: "fork" },
    ];
    if (codeBlocks.length > 0) {
        actions.push({ label: "Copy code block", value: "copy-code" });
    }
    if (hasCheckpoint) {
        actions.push({ label: "Rewind to here", value: "rewind" });
    }

    async function applyRewind(checkpoint: NovaCheckpoint): Promise<void> {
        if (!sessionId) return;
        setConfirming(null);
        try {
            const report = await restoreCheckpoint(sessionId, checkpoint.checkpoint_id);
            useScreenStore.getState().close();
            const records = await (await import("../../api/nova-api.ts")).listMessages(
                sessionId,
            );
            useChatStore.getState().loadHistory(sessionId, recordsToMessages(records));
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

    useKeyboard((key) => {
        if (!confirming) return;
        if (key.name === "y") {
            if (confirming) void applyRewind(confirming);
        } else if (key.name === "n" || key.name === "escape") {
            setConfirming(null);
        }
    });

    if (!ready) {
        return <ScreenLoading message="Loading actions..." />;
    }

    if (confirming) {
        return (
            <ScreenPanel width="50%">
                <box flexDirection="column" gap={1}>
                    <text
                        fg={theme.text.base}
                        content="Rewind to this point?"
                    />
                    <text
                        fg={theme.text.muted}
                        content={`${confirming.files} file(s) will be restored and the messages from this turn on will be dropped.`}
                    />
                    <text
                        fg={theme.text.faint}
                        content="y confirm · n cancel (files changed since the agent wrote them are skipped)"
                    />
                </box>
            </ScreenPanel>
        );
    }

    return (
        <SearchableList
            title="Message Actions"
            items={actions.map((action) => ({
                label: action.label,
                value: action.value,
            }))}
            onSelect={async (value) => {
                if (value === "edit") {
                    useEditStore.getState().set(messageId, text);
                    useScreenStore.getState().close();
                    return;
                }
                if (value === "copy") {
                    const ok = renderer.copyToClipboardOSC52(text);
                    if (ok) {
                        useToastStore.getState().show("Copied to clipboard", 2000);
                    }
                    useScreenStore.getState().close();
                    return;
                }
                if (value === "rewind") {
                    const items = await listCheckpoints(sessionId ?? "");
                    const checkpoint = items.find(
                        (item) => item.checkpoint_id === messageId,
                    );
                    if (checkpoint) setConfirming(checkpoint);
                    return;
                }
                if (value === "copy-code") {
                    if (codeBlocks.length === 1) {
                        const ok = renderer.copyToClipboardOSC52(codeBlocks[0]!);
                        if (ok) {
                            useToastStore
                                .getState()
                                .show("Copied code block", 2000);
                        }
                        useScreenStore.getState().close();
                        return;
                    }
                    useScreenStore
                        .getState()
                        .open({ kind: "copy-code-block", blocks: codeBlocks });
                    return;
                }
                if (value === "fork") {
                    if (!sessionId) return;
                    try {
                        const result = await forkSession(sessionId, messageId);
                        useScreenStore.getState().close();
                        await openSession(
                            result.session_id,
                            useChatStore.getState().agentKey,
                            undefined,
                            result.title,
                        );
                        useToastStore
                            .getState()
                            .show(
                                `Forked into “${result.title}” (${result.messages} message(s))`,
                                4000,
                            );
                    } catch (err) {
                        useToastStore
                            .getState()
                            .show(
                                `Fork failed: ${err instanceof Error ? err.message : String(err)}`,
                                4000,
                            );
                    }
                }
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText="no actions"
        />
    );
}
