/** Compaction in flight: the transcript is being summarised right now. */
import { useTheme } from "../../context/theme.tsx";
import { formatTokens } from "../../lib/status-format.ts";
import { useCompactionStore } from "../../stores/compaction-store.ts";
import { PanelHeading } from "./PanelHeading.tsx";

export function CompactingPanel() {
    const theme = useTheme();
    const compacting = useCompactionStore((state) => state.compacting);
    const messageCount = useCompactionStore((state) => state.messageCount);
    const tokenCount = useCompactionStore((state) => state.tokenCount);

    if (!compacting) return null;

    return (
        <box flexDirection="column" flexShrink={0}>
            <PanelHeading label="Compacting" />
            <text
                fg={theme.feedback.running}
                content={`${messageCount} messages · ${formatTokens(tokenCount)} tokens`}
                wrapMode="none"
            />
        </box>
    );
}
