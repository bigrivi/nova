/** Reactive theme context. Follows the terminal's dark/light mode by default;
 *  can be overridden manually via /theme. Preference is persisted to disk. */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRenderer } from "@opentui/react";
import { CliRenderEvents, type ThemeMode } from "@opentui/core";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { darkTheme, lightTheme, type Theme } from "../theme.ts";

export type ThemePreference = "system" | "dark" | "light";

const PREF_FILE = join(process.env.NOVA_HOME || join(homedir(), ".nova"), "tui-theme.json");

function readPreference(): ThemePreference {
    try {
        const raw = readFileSync(PREF_FILE, "utf-8");
        const v = JSON.parse(raw)?.preference;
        if (v === "dark" || v === "light" || v === "system") return v;
    } catch {
        // fall through
    }
    return "system";
}

function writePreference(pref: ThemePreference) {
    try {
        mkdirSync(join(process.env.NOVA_HOME || join(homedir(), ".nova")), { recursive: true });
        writeFileSync(PREF_FILE, JSON.stringify({ preference: pref }));
    } catch {
        // ignore persistence failures
    }
}

const ThemeContext = createContext<Theme>(darkTheme);
const PreferenceContext = createContext<{
    preference: ThemePreference;
    setPreference: (p: ThemePreference) => void;
}>({ preference: "system", setPreference: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
    const renderer = useRenderer();
    const [preference, setPref] = useState<ThemePreference>(readPreference);
    const [systemMode, setSystemMode] = useState<ThemeMode>(
        () => renderer.themeMode ?? "dark",
    );

    useEffect(() => {
        const handleMode = (next: ThemeMode) => setSystemMode(next);
        renderer.on(CliRenderEvents.THEME_MODE, handleMode);
        return () => {
            renderer.off(CliRenderEvents.THEME_MODE, handleMode);
        };
    }, [renderer]);

    const setPreference = (p: ThemePreference) => {
        setPref(p);
        writePreference(p);
    };

    const effectiveMode: ThemeMode =
        preference === "system" ? systemMode : preference;

    return (
        <PreferenceContext.Provider value={{ preference, setPreference }}>
            <ThemeContext.Provider value={effectiveMode === "light" ? lightTheme : darkTheme}>
                {children}
            </ThemeContext.Provider>
        </PreferenceContext.Provider>
    );
}

export function useTheme(): Theme {
    return useContext(ThemeContext);
}

export function useThemePreference(): {
    preference: ThemePreference;
    setPreference: (p: ThemePreference) => void;
} {
    return useContext(PreferenceContext);
}
