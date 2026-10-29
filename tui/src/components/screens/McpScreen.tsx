/** MCP panel: which servers loaded, which tools they gave the agent, what failed */
import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import { deleteMcpServer, listMcpServers } from "../../api/mcp.ts";
import type { NovaMcpServer } from "../../api/types.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { mcpLine, mcpToolSummary, mcpTransportLine } from "../../lib/mcp-format.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { useListScreen } from "./use-list-screen.ts";

export function McpScreen() {
    const [selected, setSelected] = useState<NovaMcpServer | null>(null);
    const [confirming, setConfirming] = useState(false);
    const { items, ready, error, reload } = useListScreen(listMcpServers);

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

    async function remove(server: NovaMcpServer): Promise<void> {
        setConfirming(false);
        try {
            await deleteMcpServer(server.name);
            setSelected(null);
            reload();
            useToastStore.getState().show(`Removed ${server.name}`, 3000);
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
        return <ScreenLoading message={error || "Loading MCP servers..."} />;
    }

    if (selected) {
        return (
            <McpDetail server={selected} confirming={confirming} />
        );
    }

    return (
        <SearchableList
            title="MCP servers"
            items={items.map((server) => ({
                label: mcpLine(server),
                value: server.name,
            }))}
            onSelect={(value) => {
                const server = items.find((entry) => entry.name === value);
                if (server) setSelected(server);
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no MCP servers configured"}
        />
    );
}

function McpDetail({
    server,
    confirming,
}: {
    server: NovaMcpServer;
    confirming: boolean;
}) {
    const theme = useTheme();
    const loaded = server.loaded_tools ?? [];
    const skipped = server.skipped_tools ?? [];

    return (
        <ScreenPanel width="75%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.text.base} content={server.name} />
                <text fg={theme.text.muted} content={mcpTransportLine(server)} />
                <text fg={theme.text.muted} content={mcpToolSummary(server)} />
                {server.env_keys.length > 0 ? (
                    <text
                        fg={theme.text.faint}
                        content={`env: ${server.env_keys.join(", ")}`}
                    />
                ) : null}
                {server.header_keys.length > 0 ? (
                    <text
                        fg={theme.text.faint}
                        content={`headers: ${server.header_keys.join(", ")}`}
                    />
                ) : null}
                {server.error ? (
                    <text fg={theme.feedback.error} content={server.error} />
                ) : null}
                <box flexDirection="column">
                    {loaded.map((tool) => (
                        <text
                            key={tool}
                            fg={theme.text.muted}
                            content={`  ${tool}`}
                        />
                    ))}
                    {skipped.map((entry) => (
                        <text
                            key={`skip-${entry.tool}`}
                            fg={theme.feedback.error}
                            content={`  ${entry.tool} — ${entry.reason}`}
                        />
                    ))}
                </box>
                <text
                    fg={confirming ? theme.feedback.error : theme.text.faint}
                    content={
                        confirming
                            ? `remove ${server.name}? y confirm · esc cancel`
                            : "d remove · esc back"
                    }
                />
            </box>
        </ScreenPanel>
    );
}
