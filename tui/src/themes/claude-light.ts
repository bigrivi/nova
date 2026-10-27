/** Claude Code inspired light theme (warm cream, Anthropic clay accent). */
import type { Theme } from "./types.ts";

export const claudeLightTheme: Theme = {
    background: {
        base: "#faf9f5",
        raised: "#f0eee6",
    },
    text: {
        base: "#191919",
        muted: "#515150",
        faint: "#6b6b6b",
    },
    primary: {
        base: "#c15f3c",
        foreground: "#000000",
        muted: "#b05839",
    },
    border: {
        base: "#ddd9cc",
    },
    feedback: {
        running: "#a8741a",
        success: "#2f8a3e",
        error: "#c0392b",
    },
    diff: {
        addedBg: "#e6f4e6",
        removedBg: "#fdeaea",
        contextBg: "#f0eee6",
        addedSign: "#2f8a3e",
        removedSign: "#c0392b",
        lineNumber: "#6b6b6b",
        addedLineNumberBg: "#e6f4e6",
        removedLineNumberBg: "#fdeaea",
    },
    markdown: {
        heading: "#c15f3c",
        code: "#b3651f",
        link: "#2f6fce",
        linkText: "#6b6b6b",
        quote: "#6b6b6b",
        bullet: "#c15f3c",
        rule: "#ddd9cc",
        strong: "#8a6d1a",
        emphasis: "#8a5a8a",
        strikethrough: "#6b6b6b",
    },
    syntax: {
        keyword: "#c15f3c",
        string: "#2f8a3e",
        comment: "#6b6b6b",
        function: "#2f6fce",
        type: "#8a6d1a",
        number: "#b3651f",
        operator: "#1f7a8c",
        punctuation: "#191919",
        variable: "#191919",
        variableBuiltin: "#191919",
        label: "#2f8a3e",
    },
};
