import { useEffect, useState } from "react";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 100;

function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

export function ThinkingSpinner() {
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
        <text fg="#d29922">
            {FRAMES[frame]} Thinking… {formatElapsed(elapsed)}
        </text>
    );
}
