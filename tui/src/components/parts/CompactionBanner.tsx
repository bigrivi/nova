import { useEffect, useState } from "react";
import { useCompactionStore } from "../../stores/compaction-store.ts";
import { theme } from "../../theme.ts";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 100;

function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function formatTokens(count: number): string {
    if (count < 1000) return String(count);
    return `${(count / 1000).toFixed(1)}k`;
}

export function CompactionBanner() {
    const compacting = useCompactionStore((s) => s.compacting);
    const messageCount = useCompactionStore((s) => s.messageCount);
    const tokenCount = useCompactionStore((s) => s.tokenCount);
    const startedAt = useCompactionStore((s) => s.startedAt);

    const [frame, setFrame] = useState(0);
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        if (!compacting || startedAt == null) {
            setFrame(0);
            setElapsed(0);
            return;
        }
        const timer = setInterval(() => {
            setFrame((f) => (f + 1) % FRAMES.length);
            setElapsed(Date.now() - startedAt);
        }, TICK_MS);
        return () => clearInterval(timer);
    }, [compacting, startedAt]);

    if (!compacting) return null;

    const detail = `${messageCount} msgs / ${formatTokens(tokenCount)}`;
    return (
        <box paddingX={2} marginBottom={1}>
            <text fg={theme.running}>
                {`${FRAMES[frame]} Compacting conversation history… ${detail} · ${formatElapsed(elapsed)}`}
            </text>
        </box>
    );
}
