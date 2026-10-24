/** Collapsible summary for consecutive exploration tool calls. */
import { useEffect, useState } from "react";
import { useTheme } from "../context/theme.tsx";
import {
    explorationCompleted,
    explorationLabel,
} from "../lib/group-parts.ts";
import type { ToolCallPart as ToolCallPartData } from "../stores/chat-store.ts";
import { ToolCallPartView } from "./parts/ToolCallPart.tsx";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function ExploredGroup({
    parts,
    expanded,
    onToggle,
}: {
    parts: ToolCallPartData[];
    expanded: boolean;
    onToggle: () => void;
}) {
    const theme = useTheme();
    const completed = explorationCompleted(parts);
    const label = explorationLabel(parts, completed);
    const [frame, setFrame] = useState(0);

    useEffect(() => {
        if (completed) return;
        const id = setInterval(
            () => setFrame((f) => (f + 1) % SPINNER_FRAMES.length),
            80,
        );
        return () => clearInterval(id);
    }, [completed]);

    const glyph = completed ? "→" : SPINNER_FRAMES[frame];

    return (
        <box flexDirection="column" marginBottom={1}>
            <box
                flexDirection="row"
                onMouseUp={() => onToggle()}
            >
                <text
                    fg={completed ? theme.muted : theme.running}
                    content={`${glyph} `}
                    flexShrink={0}
                />
                <text
                    fg={completed ? theme.muted : theme.running}
                    content={label}
                />
            </box>
            {expanded ? (
                <box flexDirection="column" marginTop={0}>
                    {parts.map((part, index) => (
                        <box key={index} gap={0} paddingLeft={2}>
                            <ToolCallPartView part={part} />
                        </box>
                    ))}
                </box>
            ) : null}
        </box>
    );
}
