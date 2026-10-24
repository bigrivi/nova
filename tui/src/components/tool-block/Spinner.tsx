import { useSyncExternalStore } from "react";
import { useTheme } from "../../context/theme.tsx";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 80;

let frame = 0;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
    listeners.add(listener);
    if (timer === null) {
        timer = setInterval(() => {
            frame = (frame + 1) % FRAMES.length;
            for (const notify of listeners) notify();
        }, TICK_MS);
    }
    return () => {
        listeners.delete(listener);
        if (listeners.size === 0 && timer !== null) {
            clearInterval(timer);
            timer = null;
        }
    };
}

function getSnapshot(): number {
    return frame;
}

export function Spinner() {
    const theme = useTheme();
    const current = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
    return <text fg={theme.running}>{FRAMES[current]}</text>;
}
