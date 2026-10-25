/** Context usage: label, ten-cell meter, percentage, and used/limit. */
import { useTheme } from "../../context/theme.tsx";
import {
    formatTokens,
    renderBar,
    type StatusDensity,
} from "../../lib/status-format.ts";

export function ContextMeter({
    used,
    limit,
    percent,
    density,
}: {
    used: number;
    limit: number;
    percent: number;
    density: StatusDensity;
}) {
    const theme = useTheme();
    const color =
        percent >= 85
            ? theme.error
            : percent >= 60
              ? theme.running
              : theme.muted;
    if (limit <= 0) {
        // No context data yet (fresh session): a zeroed meter reads as noise.
        return (
            <box flexDirection="row" alignItems="center" flexShrink={0} gap={1}>
                <text fg={theme.subtle} content="ctx" />
                <text fg={theme.muted} content="—" />
            </box>
        );
    }

    return (
        <box flexDirection="row" alignItems="center" flexShrink={0} gap={1}>
            <text fg={theme.subtle} content="ctx" />
            {density.hideBar ? null : (
                <text fg={color} marginRight={1} content={renderBar(percent)} />
            )}
            <text fg={color} content={`${percent}%`} />
            {density.hideNumbers ? null : (
                <text
                    fg={theme.muted}
                    content={`${formatTokens(used)}/${formatTokens(limit)}`}
                />
            )}
        </box>
    );
}
