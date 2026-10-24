/** Reactive theme context. Follows the terminal's dark/light mode. */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRenderer } from "@opentui/react";
import { CliRenderEvents, type ThemeMode } from "@opentui/core";
import { darkTheme, lightTheme, type Theme } from "../theme.ts";

const ThemeContext = createContext<Theme>(darkTheme);

export function ThemeProvider({ children }: { children: ReactNode }) {
    const renderer = useRenderer();
    const [mode, setMode] = useState<ThemeMode>(
        () => renderer.themeMode ?? "dark",
    );

    useEffect(() => {
        const handleMode = (next: ThemeMode) => setMode(next);
        renderer.on(CliRenderEvents.THEME_MODE, handleMode);
        return () => {
            renderer.off(CliRenderEvents.THEME_MODE, handleMode);
        };
    }, [renderer]);

    return (
        <ThemeContext.Provider value={mode === "light" ? lightTheme : darkTheme}>
            {children}
        </ThemeContext.Provider>
    );
}

export function useTheme(): Theme {
    return useContext(ThemeContext);
}
