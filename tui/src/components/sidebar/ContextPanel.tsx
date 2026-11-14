/** How full the context window is, and what the session has spent on it.
 *
 *  Two sources, one block: the window size is streamed (`data-nova-context`),
 *  the spend is read when the panel opens and again when a turn ends. They
 *  answer different questions — "how much room is left" against "what it cost
 *  to get here" — but reading them apart made the same token number look like
 *  two different numbers.
 */
import { useTheme } from "../../context/theme.tsx";
import { useSessionUsage } from "../../hooks/useSessionUsage.ts";
import { useCtxStore } from "../../stores/ctx-store.ts";
import { PanelHeading } from "./PanelHeading.tsx";

/** `~` marks a total that is missing at least one model's price. */
function money(total: number, priced: boolean): string {
    return `${priced ? "" : "~"}$${total.toFixed(2)}`;
}

export function ContextPanel() {
    const theme = useTheme();
    const used = useCtxStore((state) => state.used);
    const limit = useCtxStore((state) => state.limit);
    const percent = useCtxStore((state) => state.percent);
    const stats = useSessionUsage();

    // No window known yet (fresh session) and nothing spent: an empty block.
    const hasWindow = limit > 0;
    const hasSpend = stats !== null && stats.messages > 0;
    if (!hasWindow && !hasSpend) return null;

    return (
        <box flexDirection="column" flexShrink={0}>
            <PanelHeading label="Context" />
            {hasWindow ? (
                <text
                    fg={theme.text.muted}
                    content={`${used.toLocaleString()} tokens`}
                    wrapMode="none"
                />
            ) : null}
            {hasWindow ? (
                <text
                    fg={theme.text.muted}
                    content={`${percent}% used`}
                    wrapMode="none"
                />
            ) : null}
            {hasSpend ? (
                <text
                    fg={theme.text.muted}
                    content={`${money(stats.cost.total, stats.cost.priced)} spent · ${stats.session?.turns ?? 0} turns`}
                    wrapMode="none"
                />
            ) : null}
        </box>
    );
}
