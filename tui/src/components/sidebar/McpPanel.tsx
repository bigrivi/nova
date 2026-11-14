/** MCP servers: which loaded, which failed, and what each one offers.
 *
 *  A failed or half-loaded server is the usual reason a tool "disappeared", so
 *  the panel says it without opening a dialog. Clicking a row opens the full
 *  MCP screen.
 */
import { useEffect, useState } from "react";

import { listMcpServers } from "../../api/mcp.ts";
import type { NovaMcpServer } from "../../api/types.ts";
import { useTheme } from "../../context/theme.tsx";
import { logWarn } from "../../lib/errors.ts";
import { mcpState, mcpToolSummary } from "../../lib/mcp-format.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { PanelHeading } from "./PanelHeading.tsx";

export function McpPanel() {
    const theme = useTheme();
    const [servers, setServers] = useState<NovaMcpServer[] | null>(null);

    useEffect(() => {
        let cancelled = false;
        void listMcpServers()
            .then((next) => {
                if (!cancelled) {
                    setServers(next);
                }
            })
            .catch((err: unknown) => {
                logWarn("loading MCP servers failed", err);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    if (!servers || servers.length === 0) return null;

    const ready = servers.filter((server) => mcpState(server) === "ready").length;
    const broken = servers.filter(
        (server) => mcpState(server) === "failed",
    ).length;

    return (
        <box flexDirection="column" flexShrink={0}>
            <PanelHeading
                label="MCP"
                detail={`(${ready}/${servers.length}${broken > 0 ? `, ${broken} failed` : ""})`}
            />
            {servers.map((server) => {
                const state = mcpState(server);
                return (
                    <box
                        key={server.name}
                        flexDirection="row"
                        gap={1}
                        onMouseUp={() =>
                            useScreenStore.getState().open({ kind: "mcp" })
                        }
                    >
                        <text
                            flexShrink={0}
                            fg={
                                state === "failed"
                                    ? theme.feedback.error
                                    : state === "ready"
                                      ? theme.feedback.success
                                      : theme.text.faint
                            }
                            content="•"
                        />
                        <text
                            fg={theme.text.base}
                            content={server.name}
                            wrapMode="none"
                        />
                        <text
                            fg={theme.text.muted}
                            content={mcpToolSummary(server)}
                            wrapMode="none"
                        />
                    </box>
                );
            })}
        </box>
    );
}
