/** Facade over the application context for theme consumers. */
import { createContext, useContext, type ReactNode } from "react";
import { useApp } from "./app.tsx";
import type { Theme } from "../themes/index.ts";
import type { ThemePreference } from "../themes/preference.ts";

export type { Theme, ThemePreference };

/** A subtree-local palette, used to dim the layer behind a modal. */
const ThemeOverrideContext = createContext<Theme | null>(null);

export function ThemeOverride({
    value,
    children,
}: {
    value: Theme | null;
    children: ReactNode;
}) {
    return (
        <ThemeOverrideContext.Provider value={value}>
            {children}
        </ThemeOverrideContext.Provider>
    );
}

/** The active theme, dimmed when an ancestor `ThemeOverride` says so. */
export function useTheme(): Theme {
    const override = useContext(ThemeOverrideContext);
    const app = useApp();
    return override ?? app.theme;
}

/** Theme preference + setter + available names. */
export function useThemePreference(): {
    preference: ThemePreference;
    setPreference: (preference: ThemePreference) => void;
    available: string[];
} {
    const app = useApp();
    return {
        preference: app.themePreference,
        setPreference: app.setThemePreference,
        available: app.themeAvailable,
    };
}

/** Backwards-compatible alias for AppProvider. */
export { AppProvider as ThemeProvider } from "./app.tsx";
