/** Facade over the application context for theme consumers. */
import { useApp } from "./app.tsx";
import type { Theme } from "../themes/index.ts";
import type { ThemePreference } from "../themes/preference.ts";

export type { Theme, ThemePreference };

/** The active theme. */
export function useTheme(): Theme {
    return useApp().theme;
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
