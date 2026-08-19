/** Reasoning part: header line (Thinking…/Thought (Xs)) + reasoning content */
import type { ReasoningPart as ReasoningPartData } from "../../stores/chat-store.ts";

function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${m}m ${s}s`;
}

export function ReasoningPart({ part }: { part: ReasoningPartData }) {
    const label = part.completed
        ? part.elapsedMs != null
            ? `Thought (${formatElapsed(part.elapsedMs)})`
            : "Thought"
        : "Thinking…";
    return (
        <box flexDirection="column" marginBottom={1}>
            <text marginBottom={1} fg="#d29922">
                {label}
            </text>
            <text fg="#6e7681" content={part.text} />
        </box>
    );
}
