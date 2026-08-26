/** Semantic color tokens for the whole TUI.
 *
 * One place to change the palette; components reference meaning (muted,
 * running, error) instead of hex values, so re-theming is a single-file edit.
 */

export const theme = {
    /** App background */
    background: "#0d1117",
    /** Primary text */
    foreground: "#e6edf3",
    /** Secondary text: tool results, reasoning body, idle status */
    muted: "#6e7681",
    /** Tertiary text: tool titles in done state */
    subtle: "#8b949e",
    /** Interactive highlights: ask_user card, selection */
    accent: "#4f9cf9",
    /** In-flight work: spinner, reasoning header, busy status */
    running: "#d29922",
    /** Success */
    success: "#3fb950",
    /** Failures */
    error: "#e5534b",
    /** Filled surfaces: user message bubble, dialogs */
    surface: "#161616",
    /** Dialog backgrounds */
    surfaceDeep: "#0d1117",
    /** Borders */
    border: "#30363d",
} as const;

export type Theme = typeof theme;
