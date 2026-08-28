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

export type Theme = typeof theme;
