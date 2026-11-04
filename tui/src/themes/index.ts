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
export { nordTheme } from "./nord.ts";
export { nordLightTheme } from "./nord-light.ts";
export { gruvboxDarkTheme } from "./gruvbox-dark.ts";
export { gruvboxLightTheme } from "./gruvbox-light.ts";
export { solarizedDarkTheme } from "./solarized-dark.ts";
export { solarizedLightTheme } from "./solarized-light.ts";
export { catppuccinMochaTheme } from "./catppuccin-mocha.ts";
export { catppuccinLatteTheme } from "./catppuccin-latte.ts";
export { tokyoNightTheme } from "./tokyo-night.ts";
export { tokyoNightDayTheme } from "./tokyo-night-day.ts";
export { rosePineTheme } from "./rose-pine.ts";
export { rosePineDawnTheme } from "./rose-pine-dawn.ts";
export { everforestDarkTheme } from "./everforest-dark.ts";
export { everforestLightTheme } from "./everforest-light.ts";
export { kanagawaWaveTheme } from "./kanagawa-wave.ts";
export { kanagawaLotusTheme } from "./kanagawa-lotus.ts";

import { darkTheme } from "./dark.ts";
import { lightTheme } from "./light.ts";
import { palenightTheme } from "./palenight.ts";
import { palenightLightTheme } from "./palenight-light.ts";
import { draculaTheme } from "./dracula.ts";
import { matrixTheme } from "./matrix.ts";
import { matrixLightTheme } from "./matrix-light.ts";
import { claudeTheme } from "./claude.ts";
import { claudeLightTheme } from "./claude-light.ts";
import { nordTheme } from "./nord.ts";
import { nordLightTheme } from "./nord-light.ts";
import { gruvboxDarkTheme } from "./gruvbox-dark.ts";
import { gruvboxLightTheme } from "./gruvbox-light.ts";
import { solarizedDarkTheme } from "./solarized-dark.ts";
import { solarizedLightTheme } from "./solarized-light.ts";
import { catppuccinMochaTheme } from "./catppuccin-mocha.ts";
import { catppuccinLatteTheme } from "./catppuccin-latte.ts";
import { tokyoNightTheme } from "./tokyo-night.ts";
import { tokyoNightDayTheme } from "./tokyo-night-day.ts";
import { rosePineTheme } from "./rose-pine.ts";
import { rosePineDawnTheme } from "./rose-pine-dawn.ts";
import { everforestDarkTheme } from "./everforest-dark.ts";
import { everforestLightTheme } from "./everforest-light.ts";
import { kanagawaWaveTheme } from "./kanagawa-wave.ts";
import { kanagawaLotusTheme } from "./kanagawa-lotus.ts";
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
    nord: nordTheme,
    "nord-light": nordLightTheme,
    "gruvbox-dark": gruvboxDarkTheme,
    "gruvbox-light": gruvboxLightTheme,
    "solarized-dark": solarizedDarkTheme,
    "solarized-light": solarizedLightTheme,
    "catppuccin-mocha": catppuccinMochaTheme,
    "catppuccin-latte": catppuccinLatteTheme,
    "tokyo-night": tokyoNightTheme,
    "tokyo-night-day": tokyoNightDayTheme,
    "rose-pine": rosePineTheme,
    "rose-pine-dawn": rosePineDawnTheme,
    "everforest-dark": everforestDarkTheme,
    "everforest-light": everforestLightTheme,
    "kanagawa-wave": kanagawaWaveTheme,
    "kanagawa-lotus": kanagawaLotusTheme,
};

export const themeNames = Object.keys(themes);

export const theme = darkTheme;
export const darkThemeTokens = darkTheme;
