/** Theme contract.
 *
 *  Every value is a `#rrggbb` colour. Tokens are grouped by role and follow the
 *  shadcn/Radix convention: a surface plus a matching foreground for whatever
 *  is drawn on it. Names state the job, not the shade.
 */
export type Theme = {
    /** Layers, lightest job first: the canvas, then raised panels. */
    background: {
        /** Application canvas. Everything else is drawn on it. */
        base: string;
        /** One step above the canvas: modal panels, user bubbles, cards. */
        raised: string;
    };
    /** Neutral text, three emphasis levels. */
    text: {
        /** Body copy: the highest-contrast neutral. */
        base: string;
        /** Secondary copy at AA contrast: group labels, footers, hints. */
        muted: string;
        /** Decoration only (placeholders, disabled copy); may fall under 4.5:1. */
        faint: string;
    };
    /** The one strong accent: selection, focus and brand marks. */
    primary: {
        /** Fill: cursor band, current-item dot, focus rings, titles. */
        base: string;
        /** Text and glyphs drawn on `base`; at least 4.5:1 against it. */
        foreground: string;
        /** `base` shifted for use as text on the background (labels, headers);
         *  same hue family as `base`, at least 4.5:1 on the canvas. */
        muted: string;
    };
    /** Hairlines around panels, dividers and inactive borders. */
    border: {
        base: string;
    };
    /** Status colours; each is text/glyph only, never a fill. */
    feedback: {
        success: string;
        error: string;
        /** A tool or turn is still running. */
        running: string;
    };
    /** Diff bodies: line backgrounds, gutter signs and line numbers. */
    diff: {
        addedBg: string;
        removedBg: string;
        contextBg: string;
        addedSign: string;
        removedSign: string;
        lineNumber: string;
        addedLineNumberBg: string;
        removedLineNumberBg: string;
    };
    /** Markdown roles. Headers in dialogs are `primary.muted`, not `heading`:
     *  this group is content, that one is chrome. */
    markdown: {
        heading: string;
        code: string;
        link: string;
        /** The URL printed after a link label. */
        linkText: string;
        quote: string;
        bullet: string;
        rule: string;
        strong: string;
        emphasis: string;
        strikethrough: string;
    };
    /** Syntax highlighting, one role per token class. */
    syntax: {
        comment: string;
        keyword: string;
        function: string;
        string: string;
        number: string;
        type: string;
        operator: string;
        punctuation: string;
        variable: string;
        variableBuiltin: string;
        label: string;
    };
};
