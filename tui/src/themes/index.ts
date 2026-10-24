export type { Theme } from "./types.ts";
export { darkTheme } from "./dark.ts";
export { lightTheme } from "./light.ts";
export { palenightTheme } from "./palenight.ts";
export { palenightLightTheme } from "./palenight-light.ts";
export { draculaTheme } from "./dracula.ts";
export { matrixTheme } from "./matrix.ts";
export { matrixLightTheme } from "./matrix-light.ts";
export { claudeTheme } from "./claude.ts";
export { claudeLightTheme } from "./claude-light.ts";

import { darkTheme } from "./dark.ts";
import { lightTheme } from "./light.ts";
import { palenightTheme } from "./palenight.ts";
import { palenightLightTheme } from "./palenight-light.ts";
import { draculaTheme } from "./dracula.ts";
import { matrixTheme } from "./matrix.ts";
import { matrixLightTheme } from "./matrix-light.ts";
import { claudeTheme } from "./claude.ts";
import { claudeLightTheme } from "./claude-light.ts";
import type { Theme } from "./types.ts";

export const themes: Record<string, Theme> = {
    dark: darkTheme,
    light: lightTheme,
    palenight: palenightTheme,
    "palenight-light": palenightLightTheme,
    dracula: draculaTheme,
    matrix: matrixTheme,
    "matrix-light": matrixLightTheme,
    claude: claudeTheme,
    "claude-light": claudeLightTheme,
};

export const themeNames = Object.keys(themes);

export const theme = darkTheme;
export const darkThemeTokens = darkTheme;
