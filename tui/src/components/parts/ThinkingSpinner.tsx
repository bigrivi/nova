import { useEffect, useState } from "react";
import { useTheme } from "../../context/theme.tsx";
import { useChatStore, type RetryState } from "../../stores/chat-store.ts";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 100;
/** Keep the retry line on one row: the upstream reason can be a whole URL+error. */
const REASON_MAX = 60;

function formatElapsed(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

/** " · retry 1/6 in 60s · HTTP 429", or "" while the model is just thinking. */
export function retrySuffix(retry: RetryState | null): string {
    if (!retry) return "";
    const budget = retry.total > 0 ? `${retry.attempt}/${retry.total}` : `${retry.attempt}`;
    const wait =
        retry.waitSeconds > 0 ? ` in ${Math.round(retry.waitSeconds)}s` : "";
    const raw = retry.reason.trim();
    const reason = raw.length > REASON_MAX ? `${raw.slice(0, REASON_MAX - 1)}…` : raw;
    return ` · retry ${budget}${wait}${reason ? ` · ${reason}` : ""}`;
}

export function ThinkingSpinner() {
    const theme = useTheme();
    const retry = useChatStore((state) => state.retry);
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
        <text fg={theme.feedback.running} marginTop={1}>
            {FRAMES[frame]} Thinking… {formatElapsed(elapsed)}
            {retrySuffix(retry)}
        </text>
    );
}
