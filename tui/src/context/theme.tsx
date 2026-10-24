/** Reactive theme context. Defaults to the built-in theme. */
import { createContext, useContext, useState, type ReactNode } from "react";
import { theme as defaultTheme, type Theme } from "../theme.ts";

const ThemeContext = createContext<Theme>(defaultTheme);

export function ThemeProvider({ children }: { children: ReactNode }) {
    const [current] = useState<Theme>(defaultTheme);
    return <ThemeContext.Provider value={current}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
    return useContext(ThemeContext);
}
