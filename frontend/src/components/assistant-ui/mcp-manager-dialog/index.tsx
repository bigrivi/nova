import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2Icon, PencilIcon, PlusIcon } from "lucide-react";

import { listMcpServers } from "../../../lib/nova-api";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";
import { McpServerDialog } from "./server-dialog";
import {
    serverTarget,
    type NovaMcpServerRecord,
} from "./types";

/** Stand-in when the host surface has no status bar to report to. */
function noopStatus() {
    /* nothing to report to */
}

/**
 * Whether a configured server is actually serving tools right now.
 *
 * A dot rather than a badge: the tool count already has a line of its own below,
 * and a row of numbers is noise next to the name it describes. The reason a
 * server is unreachable is spelled out underneath in words, so the dot only has
 * to answer "is this one working" at a glance. The title carries the same answer
 * for anyone hovering.
 */
function StatusBadge({ server }: { server: NovaMcpServerRecord }) {
    const { t } = useTranslation();
    const dot = (color: string, label: string) => (
        <span
            className={cn("size-2 shrink-0 rounded-full", color)}
            title={label}
            role="img"
            aria-label={label}
        />
    );
    if (server.error) {
        return dot("bg-destructive", t("mcp.statusFailed"));
    }
    if (server.loaded_tools === null) {
        return dot("bg-muted-foreground/40", t("mcp.statusUnknown"));
    }
    return dot("bg-emerald-500", t("mcp.statusConnected"));
}

export type McpManagerContentProps = {
    /**
     * Reports a save/delete failure to the settings dialog's status bar, so a
     * failed write is not confined to a dialog the user already dismissed.
     * Optional: the list renders its own load error regardless.
     */
    onStatusChange?: (message: string | null) => void;
};

/**
 * The MCP settings section: the configured servers, and the one button that
 * matters most here -- add a server, then prove it connects before saving.
 */
export function McpManagerContent({
    onStatusChange,
}: McpManagerContentProps = {}) {
    const { t } = useTranslation();
    const [servers, setServers] = useState<NovaMcpServerRecord[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [editing, setEditing] = useState<NovaMcpServerRecord | undefined>();
    const [adding, setAdding] = useState(false);

    // Loaded once on mount. Every mutation returns the fresh list, so nothing
    // here needs to re-read it.
    useEffect(() => {
        let cancelled = false;
        listMcpServers()
            .then((next) => {
                if (!cancelled) setServers(next);
            })
            .catch((error: unknown) => {
                if (!cancelled) {
                    setLoadError(
                        error instanceof Error ? error.message : String(error),
                    );
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    return (
        <div className="flex h-full min-h-0 min-w-0 flex-col gap-4">
            <div className="flex shrink-0 items-start justify-between gap-4">
                <div className="min-w-0">
                    <h3 className="text-[14px] font-semibold">
                        {t("mcp.title")}
                    </h3>
                    <p className="mt-1 text-[13px] text-muted-foreground">
                        {t("mcp.description")}
                    </p>
                </div>
                <Button
                    type="button"
                    size="sm"
                    className="gap-1.5 shrink-0"
                    onClick={() => setAdding(true)}
                >
                    <PlusIcon className="size-4" />
                    {t("mcp.add")}
                </Button>
            </div>

            {loading ? (
                <p className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                    <Loader2Icon className="size-4 animate-spin" />
                    {t("common.loading")}
                </p>
            ) : loadError ? (
                <p className="py-6 text-center text-sm text-destructive">
                    {loadError}
                </p>
            ) : servers.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                    {t("mcp.empty")}
                </p>
            ) : (
                <div className="flex flex-col gap-2 overflow-y-auto pr-1">
                    {servers.map((server) => (
                        <div
                            key={server.name}
                            className="flex items-start justify-between gap-3 rounded-lg border bg-card p-3"
                        >
                            <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="truncate text-sm font-medium">
                                        {server.name}
                                    </span>
                                    <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                        {t(`mcp.transport_${server.transport}`)}
                                    </span>
                                    <StatusBadge server={server} />
                                </div>
                                <p className="mt-1 font-mono text-xs break-all text-muted-foreground">
                                    {serverTarget(server)}
                                </p>
                                {/* A server that cannot be reached has no tools
                                    at all, so this is the only symptom there is.
                                    Without it the tools just stop existing. */}
                                {server.error ? (
                                    <p className="mt-1 text-[11px] break-words text-destructive">
                                        {t("mcp.connectionFailed", {
                                            reason: server.error,
                                        })}
                                    </p>
                                ) : null}
                                {server.env_keys.length > 0 ||
                                server.header_keys.length > 0 ? (
                                    <p className="mt-1 text-[11px] text-muted-foreground/70">
                                        {t("mcp.secretNames", {
                                            names: [
                                                ...server.env_keys,
                                                ...server.header_keys,
                                            ].join(", "),
                                        })}
                                    </p>
                                ) : null}
                                {/* What the agent can reach, which the connection
                                    test cannot tell the user: a server can connect
                                    and still offer tools no agent will ever see. */}
                                {server.loaded_tools !== null &&
                                server.loaded_tools.length > 0 ? (
                                    <p className="mt-1 text-[11px] text-muted-foreground">
                                        {t("mcp.loadedTools", {
                                            count: server.loaded_tools.length,
                                        })}
                                    </p>
                                ) : null}
                                {(server.skipped_tools ?? []).map((entry) => (
                                    <p
                                        key={entry.tool}
                                        className="mt-1 text-[11px] text-destructive"
                                    >
                                        {t("mcp.skippedTool", {
                                            tool: entry.tool,
                                            reason: entry.reason,
                                        })}
                                    </p>
                                ))}
                            </div>
                            <Button
                                type="button"
                                size="icon-sm"
                                variant="ghost"
                                className="shrink-0"
                                aria-label={t("mcp.manage", {
                                    name: server.name,
                                })}
                                onClick={() => setEditing(server)}
                            >
                                <PencilIcon className="size-4" />
                            </Button>
                        </div>
                    ))}
                </div>
            )}

            <p className="shrink-0 rounded-lg bg-muted/40 px-3 py-2 text-[11px] leading-snug text-muted-foreground">
                {t("mcp.reloadNotice")}
            </p>

            {adding ? (
                <McpServerDialog
                    open={adding}
                    onOpenChange={setAdding}
                    onStatusChange={onStatusChange ?? noopStatus}
                    onMutated={(next) => {
                        setServers(next);
                        setAdding(false);
                    }}
                />
            ) : null}
            {editing ? (
                <McpServerDialog
                    key={editing.name}
                    open
                    server={editing}
                    onStatusChange={onStatusChange ?? noopStatus}
                    onOpenChange={(open) => {
                        if (!open) setEditing(undefined);
                    }}
                    onMutated={(next) => {
                        setServers(next);
                        setEditing(undefined);
                    }}
                />
            ) : null}
        </div>
    );
}