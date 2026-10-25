import { useEffect, useState } from "react";
import { useTheme } from "../../context/theme.tsx";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 100;

function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

export function ThinkingSpinner() {
    const theme = useTheme();
    const [frame, setFrame] = useState(0);
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        const start = Date.now();
        const timer = setInterval(() => {
            setFrame((f) => (f + 1) % FRAMES.length);
            setElapsed(Date.now() - start);
        }, TICK_MS);
        return () => clearInterval(timer);
    }, []);

    return (
        <text fg={theme.running} marginTop={1}>
            {FRAMES[frame]} Thinking… {formatElapsed(elapsed)}
        </text>
    );
}
