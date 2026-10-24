export type { Theme } from "./types.ts";
export { darkTheme } from "./dark.ts";
export { lightTheme } from "./light.ts";
export { palenightTheme } from "./palenight.ts";
export { draculaTheme } from "./dracula.ts";

import { darkTheme } from "./dark.ts";
import { lightTheme } from "./light.ts";
import { palenightTheme } from "./palenight.ts";
import { draculaTheme } from "./dracula.ts";
import type { Theme } from "./types.ts";

export const themes: Record<string, Theme> = {
    dark: darkTheme,
    light: lightTheme,
    palenight: palenightTheme,
    dracula: draculaTheme,
};

export const themeNames = Object.keys(themes);

export const theme = darkTheme;
export const darkThemeTokens = darkTheme;
