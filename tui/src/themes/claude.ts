/** Claude Code inspired theme (warm dark, Anthropic clay accent). */
import type { Theme } from "./types.ts";

export const claudeTheme: Theme = {
    background: {
        base: "#1f1e1d",
        raised: "#353433",
    },
    text: {
        base: "#e5e5e5",
        muted: "#aaa9a9",
        faint: "#8a8a8a",
    },
    primary: {
        base: "#d97757",
        foreground: "#1f1e1d",
        muted: "#d97757",
    },
    border: {
        base: "#3a3a3a",
    },
    feedback: {
        running: "#e5a35e",
        success: "#7cbf6b",
        error: "#ff6b6b",
    },
    diff: {
        addedBg: "#1e2f1e",
        removedBg: "#2f1e1e",
        contextBg: "#2a2928",
        addedSign: "#7cbf6b",
        removedSign: "#ff6b6b",
        lineNumber: "#8a8a8a",
        addedLineNumberBg: "#1e2f1e",
        removedLineNumberBg: "#2f1e1e",
    },
    markdown: {
        heading: "#d97757",
        code: "#d9a56a",
        link: "#6ba3ff",
        linkText: "#8a8a8a",
        quote: "#8a8a8a",
        bullet: "#d97757",
        rule: "#5e5e5e",
        strong: "#e5c07b",
        emphasis: "#b0b0b0",
        strikethrough: "#8a8a8a",
    },
    syntax: {
        keyword: "#d97757",
        string: "#98c379",
        comment: "#7a7a7a",
        function: "#61afef",
        type: "#e5c07b",
        number: "#d19a66",
        operator: "#56b6c2",
        punctuation: "#abb2bf",
        variable: "#e5e5e5",
        variableBuiltin: "#e5e5e5",
        label: "#98c379",
    },
};
