/** Theme contract.
 *
 *  Every value is a `#rrggbb` colour. The names follow the shadcn/ui and
 *  Radix conventions: a surface token plus a matching `*Foreground` token for
 *  whatever is drawn on top of it.
 */
export type Theme = {
    /** Application canvas. Everything else is layered on it. */
    background: string;
    /** Default body text and icons on `background`. Highest-emphasis neutral. */
    foreground: string;
    /** Secondary text on `background` (group labels, helper text): quieter than
     *  `foreground` but still at least 4.5:1, unlike `muted`. */
    foregroundMuted: string;
    /** Low-emphasis text such as placeholders and disabled copy. May fall under
     *  4.5:1, so never use it for information the user has to read. */
    muted: string;
    /** Third neutral step for de-emphasised marks and separators in text. */
    subtle: string;
    /** Brand/accent fill: focus, current item, selected row background. */
    accent: string;
    /** Text and glyphs drawn on `accent`; guaranteed at least 4.5:1 against it. */
    accentForeground: string;
    /** Accent hue shifted for use as *text* on `background` (group labels, section
     *  titles): at least 4.5:1, so it never inherits the accent's fill contrast. */
    accentText: string;
    /** Activity indicator (spinner, running task). */
    running: string;
    /** Success state text and glyphs. */
    success: string;
    /** Error state text and glyphs. */
    error: string;
    /** Raised surface (cards, user bubbles, panels) on `background`. */
    surface: string;
    /** Deepest/raised modal surface; content sits here rather than on `background`. */
    surfaceDeep: string;
    /** Hairlines around panels, dividers and inactive borders. */
    border: string;

    /** Diff body backgrounds for added/removed/context lines. */
    diff: {
        addedBg: string;
        removedBg: string;
        contextBg: string;
        /** +/− gutter signs. */
        addedSign: string;
        removedSign: string;
        /** Line numbers and their gutter backgrounds, including per-sign variants. */
        lineNumber: string;
        lineNumberBg: string;
        addedLineNumberBg: string;
        removedLineNumberBg: string;
    };

    /** Markdown headings. Content role, not chrome: list/group labels use
     *  `foregroundMuted` instead. */
    heading: string;
    /** Inline code spans. */
    codeInline: string;
    /** Link label. */
    link: string;
    /** Link target printed next to the label. */
    linkUrl: string;
    /** Block quote text. */
    quote: string;
    /** List bullets and ordered-list numbers. */
    bullet: string;
    /** Horizontal rules. */
    rule: string;
    /** Bold text. */
    strong: string;
    /** Italic text. */
    italic: string;
    /** Struck-through text. */
    strikethrough: string;

    /** Syntax highlighting, one role per token class. */
    syntaxKeyword: string;
    syntaxString: string;
    syntaxComment: string;
    syntaxFunction: string;
    syntaxType: string;
    syntaxNumber: string;
    syntaxOperator: string;
    syntaxPunctuation: string;
    syntaxVariable: string;
    syntaxVariableBuiltin: string;
    syntaxLabel: string;
};
