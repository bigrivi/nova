/** `/stats`: tokens and estimated cost, for this session or every session. */
import { useKeyboard } from "@opentui/react";
import { useState } from "react";
import { fetchStats } from "../../api/stats.ts";
import type { NovaStats } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { truncateMiddle } from "../../lib/display-width.ts";
import { compactTokens, formatCost, formatDuration } from "../../lib/stats-format.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";
import { useListScreen } from "./use-list-screen.ts";

/** How many models fit before the list is cut. */
const MAX_MODELS = 8;

type Scope = "session" | "all";

export function StatsScreen() {
    const theme = useTheme();
    const sessionId = useChatStore((state) => state.sessionId);
    const [scope, setScope] = useState<Scope>("session");
    const { items, ready, error, reload } = useListScreen(
        () => load(scope),
        (rows) => rows[0]?.scope,
    );

    useKeyboard((key) => {
        if (key.name === "escape" || key.name === "q") {
            useScreenStore.getState().close();
            return;
        }
        const next: Scope | null =
            key.name === "s" ? "session" : key.name === "a" ? "all" : null;
        if (next && next !== scope) {
            // The loader is pinned to the first render; asking again is what
            // makes it read the scope that was just chosen.
            setScope(next);
            reload();
        }
    });

    function load(next: Scope): Promise<NovaStats[]> {
        if (next === "session" && !sessionId) return Promise.resolve([]);
        return fetchStats(next === "session" ? sessionId : null).then((stats) => [stats]);
    }

    const stats = items[0];
    if (!ready) {
        return <ScreenLoading message={error || "Counting tokens..."} />;
    }
    if (!stats) {
        return (
            <ScreenLoading
                message={error || "No open session: nothing to count yet"}
            />
        );
    }

    const scopeLabel =
        stats.scope === "session" ? "this session" : "every session";
    const facts = stats.session
        ? `${stats.session.turns} turns · ${stats.session.messages} messages · ` +
          formatDuration(stats.session.updated_at - stats.session.started_at)
        : `${stats.messages} replies`;

    return (
        <ScreenPanel width="60%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.primary.muted} content="Stats" />
                <text
                    fg={theme.text.muted}
                    content={`Scope: ${scopeLabel} · ${facts}`}
                />

                <text fg={theme.text.faint} content="Tokens" />
                <box flexDirection="column">
                    <text
                        fg={theme.text.base}
                        content={`  input        ${compactTokens(stats.tokens.input)}`}
                    />
                    <text
                        fg={theme.text.base}
                        content={`  output       ${compactTokens(stats.tokens.output)}`}
                    />
                    <text
                        fg={theme.text.base}
                        content={`  cache read   ${compactTokens(stats.tokens.cache_read)}`}
                    />
                    <text
                        fg={theme.text.base}
                        content={`  total        ${compactTokens(stats.tokens.total)}`}
                    />
                </box>

                <text
                    fg={theme.text.base}
                    content={`Cost (estimate)   ${formatCost(stats.cost.total)}${
                        stats.cost.unpriced_models > 0
                            ? `  ·  ${stats.cost.unpriced_models} model(s) with no known price`
                            : ""
                    }`}
                />

                {stats.by_model.length > 0 ? (
                    <box flexDirection="column">
                        <text fg={theme.text.faint} content="By model" />
                        {stats.by_model.slice(0, MAX_MODELS).map((row) => (
                            <text
                                key={row.model || "(none)"}
                                fg={theme.text.base}
                                content={
                                    `${truncateMiddle(row.model || "(no model)", 28).padEnd(28)}` +
                                    `${compactTokens(row.input).padStart(6)} in` +
                                    `${compactTokens(row.output).padStart(6)} out` +
                                    `${formatCost(row.cost).padStart(7)}`
                                }
                            />
                        ))}
                        {stats.by_model.length > MAX_MODELS ? (
                            <text
                                fg={theme.text.faint}
                                content={`  … ${stats.by_model.length - MAX_MODELS} more`}
                            />
                        ) : null}
                    </box>
                ) : null}

                <text
                    fg={theme.text.faint}
                    content="s this session · a every session · esc close"
                />
            </box>
        </ScreenPanel>
    );
}
