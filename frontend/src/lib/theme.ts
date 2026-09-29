import { useEffect, useState } from "react";

export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "nova.ui.theme-mode";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const MODES: readonly ThemeMode[] = ["light", "dark", "system"];

function isThemeMode(value: unknown): value is ThemeMode {
    return (
        typeof value === "string" &&
        (MODES as readonly string[]).includes(value)
    );
}

/** Last saved mode, defaulting to the operating system. */
export function readThemeMode(): ThemeMode {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (isThemeMode(raw)) return raw;
    } catch {
        /* Storage unavailable (private mode): fall through to system. */
    }
    return "system";
}

function systemIsDark(): boolean {
    return (
        typeof window !== "undefined" &&
        typeof window.matchMedia === "function" &&
        window.matchMedia(DARK_QUERY).matches
    );
}

/** Resolve a mode to the concrete theme the page should render. */
export function resolveTheme(mode: ThemeMode): "light" | "dark" {
    if (mode === "dark") return "dark";
    if (mode === "light") return "light";
    return systemIsDark() ? "dark" : "light";
}

/** Persist the mode and flip the document theme immediately. */
export function applyThemeMode(mode: ThemeMode): void {
    try {
        localStorage.setItem(STORAGE_KEY, mode);
    } catch {
        /* Ignore write failures; the in-memory theme still applies. */
    }
    document.documentElement.classList.toggle(
        "dark",
        resolveTheme(mode) === "dark",
    );
}

/** Reactive mode for the settings control; follows the OS while "system". */
export function useThemeMode(): {
    mode: ThemeMode;
    setMode: (mode: ThemeMode) => void;
} {
    const [mode, setModeState] = useState<ThemeMode>(() => readThemeMode());

    useEffect(() => {
        applyThemeMode(mode);
    }, [mode]);

    useEffect(() => {
        if (mode !== "system") return;
        const list = window.matchMedia(DARK_QUERY);
        const onChange = () => applyThemeMode("system");
        list.addEventListener("change", onChange);
        return () => list.removeEventListener("change", onChange);
    }, [mode]);

    return {
        mode,
        setMode: (next: ThemeMode) => setModeState(next),
    };
}
