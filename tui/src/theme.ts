/** Semantic color tokens for the whole TUI.
 *
 * One place to change the palette; components reference meaning (muted,
 * running, error) instead of hex values, so re-theming is a single-file edit.
 */

export const darkTheme = {
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
    /** Diff rendering tokens */
    diff: {
        addedBg: "#162a1a",
        removedBg: "#2a1616",
        contextBg: "#161616",
        addedSign: "#3fb950",
        removedSign: "#e5534b",
        lineNumber: "#6e7681",
        lineNumberBg: "#161616",
        addedLineNumberBg: "#162a1a",
        removedLineNumberBg: "#2a1616",
    },
    // ── Markdown semantic tokens (consumed by MarkdownPart syntaxStyle) ──
    /** Headings h1..h6 — distinct from body, bold via syntaxStyle */
    heading: "#79c0ff",
    /** Inline `code` span */
    codeInline: "#d2a8ff",
    /** Link label text — underlined via syntaxStyle */
    link: "#4f9cf9",
    /** Link URL inside (parentheses) — muted but still distinct */
    linkUrl: "#8b949e",
    /** Blockquote body — italic + muted */
    quote: "#8b949e",
    /** List bullet/number marker */
    bullet: "#79c0ff",
    /** Horizontal rule */
    rule: "#484f58",
    /** Bold text */
    strong: "#ffa657",
    /** Italic text */
    italic: "#d2a8ff",
    /** Strikethrough */
    strikethrough: "#8b949e",

    // ── Code-block syntax tokens (tree-sitter) — single source of truth ──
    syntaxKeyword: "#ff7b72",
    syntaxString: "#a5d6ff",
    syntaxComment: "#8b949e",
    syntaxFunction: "#d2a8ff",
    syntaxType: "#ffa657",
    syntaxNumber: "#79c0ff",
    syntaxOperator: "#ff7b72",
    syntaxPunctuation: "#c9d1d9",
    syntaxVariable: "#e6edf3",
    syntaxVariableBuiltin: "#e6edf3",
    syntaxLabel: "#a5d6ff",
} as const;

export type Theme = {
    [K in keyof typeof darkTheme]: (typeof darkTheme)[K] extends string
        ? string
        : { [P in keyof (typeof darkTheme)[K]]: string };
};

export const lightTheme: Theme = {
    ...darkTheme,
    background: "#f6f8fa",
    foreground: "#1f2328",
    muted: "#656d76",
    subtle: "#57606a",
    accent: "#0969da",
    running: "#9a6700",
    success: "#1a7f37",
    error: "#cf222e",
    surface: "#eaeef2",
    surfaceDeep: "#f6f8fa",
    border: "#d0d7de",
    diff: {
        addedBg: "#e6ffec",
        removedBg: "#ffebe9",
        contextBg: "#f6f8fa",
        addedSign: "#1a7f37",
        removedSign: "#cf222e",
        lineNumber: "#656d76",
        lineNumberBg: "#f6f8fa",
        addedLineNumberBg: "#ccffd8",
        removedLineNumberBg: "#ffd7d5",
    },
    heading: "#0550ae",
    codeInline: "#8250df",
    link: "#0969da",
    linkUrl: "#57606a",
    quote: "#57606a",
    bullet: "#0550ae",
    rule: "#d0d7de",
    strong: "#953800",
    italic: "#8250df",
    strikethrough: "#57606a",
    syntaxKeyword: "#cf222e",
    syntaxString: "#0a3069",
    syntaxComment: "#6e7781",
    syntaxFunction: "#8250df",
    syntaxType: "#953800",
    syntaxNumber: "#0550ae",
    syntaxOperator: "#cf222e",
    syntaxPunctuation: "#24292f",
    syntaxVariable: "#24292f",
    syntaxVariableBuiltin: "#24292f",
    syntaxLabel: "#0a3069",
};

export const darkThemeTokens = darkTheme;
export const theme = darkTheme;
