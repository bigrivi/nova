/** Status dot: idle ring, animated spinner while working, coloured dot when
 *  waiting on the user or after a failure. */
import { useEffect, useState } from "react";
import { useTheme } from "../../context/theme.tsx";
import type { AgentStatus } from "../../lib/status.ts";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 80;

export function StatusGlyph({ status }: { status: AgentStatus }) {
    const theme = useTheme();
    const [frame, setFrame] = useState(0);

    useEffect(() => {
        if (status !== "running") {
            setFrame(0);
            return;
        }
        const timer = setInterval(
            () => setFrame((value) => (value + 1) % FRAMES.length),
            TICK_MS,
        );
        return () => clearInterval(timer);
    }, [status]);

    if (status === "running") {
        return <text fg={theme.accent}>{FRAMES[frame]}</text>;
    }

    const content =  "●";
    const color =
        status === "waiting"
            ? theme.running
            : status === "error"
              ? theme.error
              : theme.muted;
    return <text fg={color}>{content}</text>;
}
