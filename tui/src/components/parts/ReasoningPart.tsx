/** Reasoning part: header line (Thinking…/Thought (Xs)) + reasoning content */
import { RGBA } from "@opentui/core";
import { useTheme } from "../../context/theme.tsx";
import type { ReasoningPart as ReasoningPartData } from "../../stores/chat-store.ts";

function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${m}m ${s}s`;
}

export function ReasoningPart({ part }: { part: ReasoningPartData }) {
    const theme = useTheme();
    // OpenCode renders the expanded "Thought" label as warning at 60% opacity.
    const warning = RGBA.fromHex(theme.running);
    const thoughtFg = RGBA.fromValues(warning.r, warning.g, warning.b, 0.6);
    const label = part.completed
        ? part.elapsedMs != null
            ? `Thought (${formatElapsed(part.elapsedMs)})`
            : "Thought"
        : "Thinking…";
    return (
        <box flexDirection="column" marginBottom={1} marginLeft={2}>
            <text marginBottom={1} fg={thoughtFg}>
                {label}
            </text>
            <box
                border={["left"]}
                borderColor={theme.surface}
                paddingLeft={1}
            >
                <text fg={theme.muted} content={part.text} />
            </box>
        </box>
    );
}
