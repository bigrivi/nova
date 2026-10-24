/** Reactive theme context. Supports named themes plus "system" (follow terminal). */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRenderer } from "@opentui/react";
import { CliRenderEvents, type ThemeMode } from "@opentui/core";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { themes, themeNames, darkTheme, lightTheme, type Theme } from "../themes/index.ts";

export type ThemePreference = string; // theme name or "system"

const PREF_FILE = join(process.env.NOVA_HOME || join(homedir(), ".nova"), "tui-theme.json");

function readPreference(): ThemePreference {
    try {
        const raw = readFileSync(PREF_FILE, "utf-8");
        const v = JSON.parse(raw)?.preference;
        if (v === "system" || (typeof v === "string" && v in themes)) return v;
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
    available: string[];
}>({ preference: "system", setPreference: () => {}, available: themeNames });

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

    let theme: Theme;
    if (preference === "system") {
        theme = systemMode === "light" ? lightTheme : darkTheme;
    } else if (preference in themes) {
        theme = themes[preference]!;
    } else {
        theme = darkTheme;
    }

    return (
        <PreferenceContext.Provider value={{ preference, setPreference, available: ["system", ...themeNames] }}>
            <ThemeContext.Provider value={theme}>
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
    available: string[];
} {
    return useContext(PreferenceContext);
}
