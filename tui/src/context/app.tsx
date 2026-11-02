/** Single application context: theme, catalog, and other process-wide values.
 *
 * New shared values go here (and on AppContextValue) instead of adding another
 * provider. Consumers read slices through the facades in context/theme.tsx and
 * context/catalog.tsx, so most call sites never change.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRenderer } from "@opentui/react";
import { CliRenderEvents, type ThemeMode } from "@opentui/core";
import { themes, themeNames, darkTheme, lightTheme, type Theme } from "../themes/index.ts";
import {
    readPreference,
    writePreference,
    type ThemePreference,
} from "../themes/preference.ts";
import { loadCatalog, resetCatalog, type Catalog } from "../lib/catalog.ts";
import {
    refreshRegistry,
    syncProviderModels,
} from "../api/nova-api.ts";
import { readGitBranch } from "../lib/git-branch.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

export type AppContextValue = {
    theme: Theme;
    themePreference: ThemePreference;
    setThemePreference: (preference: ThemePreference) => void;
    themeAvailable: string[];
    catalog: Catalog | null;
    /** Refetch after a config write, e.g. after connecting a provider. */
    reloadCatalog: () => Promise<void>;
    branch: string | null;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
    const renderer = useRenderer();
    const [themePreference, setPreferenceState] = useState<ThemePreference>(
        readPreference,
    );
    const [systemMode, setSystemMode] = useState<ThemeMode>(
        () => renderer.themeMode ?? "dark",
    );
    const [catalog, setCatalog] = useState<Catalog | null>(null);
    const [branch, setBranch] = useState<string | null>(null);

    useEffect(() => {
        const handleMode = (next: ThemeMode) => setSystemMode(next);
        renderer.on(CliRenderEvents.THEME_MODE, handleMode);
        return () => {
            renderer.off(CliRenderEvents.THEME_MODE, handleMode);
        };
    }, [renderer]);

    useEffect(() => {
        setBranch(readGitBranch(WORKSPACE_DIR));
    }, []);

    useEffect(() => {
        let cancelled = false;
        void loadCatalog()
            .then((next) => {
                if (!cancelled) setCatalog(next);
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    // Refresh the provider catalogues once per TUI launch. A backend outlives
    // the client, so doing this on the server would only ever run on the first
    // window of the day; the moment the user means by "restart" is this one.
    // It must never delay the first frame, and a provider that is down is not
    // the user's problem until they look at the list.
    useEffect(() => {
        let cancelled = false;
        // One fetch from models.dev feeds both the model specs and the vendor
        // list; the daily cache makes a restart cheap.
        void refreshRegistry().catch(() => {});
        void syncProviderModels()
            .then((result) => {
                if (cancelled || result.synced.length === 0) return;
                resetCatalog();
                return loadCatalog().then((next) => {
                    if (!cancelled) setCatalog(next);
                });
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    const reloadCatalog = async () => {
        // The catalog is a process-lifetime cache, which is right for labels but
        // wrong after the TUI itself changes config.json: connecting a provider
        // would otherwise only appear after a restart.
        resetCatalog();
        setCatalog(await loadCatalog());
    };

    const setThemePreference = (preference: ThemePreference) => {
        setPreferenceState(preference);
        writePreference(preference);
    };

    const theme: Theme =
        themePreference === "system"
            ? systemMode === "light"
                ? lightTheme
                : darkTheme
            : themes[themePreference] ?? darkTheme;

    const value: AppContextValue = {
        theme,
        themePreference,
        setThemePreference,
        themeAvailable: ["system", ...themeNames],
        catalog,
        reloadCatalog,
        branch,
    };

    return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
    const value = useContext(AppContext);
    if (value === null) {
        throw new Error("useApp must be used within AppProvider");
    }
    return value;
}

