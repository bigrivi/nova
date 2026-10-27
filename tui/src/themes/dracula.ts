/** Dracula theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const draculaTheme: Theme = {
    background: {
        base: "#282a36",
        raised: "#21222c",
    },
    text: {
        base: "#f8f8f2",
        muted: "#bababa",
        faint: "#6272a4",
    },
    primary: {
        base: "#bd93f9",
        foreground: "#282a36",
        muted: "#bd93f9",
    },
    border: {
        base: "#44475a",
    },
    feedback: {
        running: "#f1fa8c",
        success: "#50fa7b",
        error: "#ff5555",
    },
    diff: {
        addedBg: "#1a3a1a",
        removedBg: "#3a1a1a",
        contextBg: "#21222c",
        addedSign: "#50fa7b",
        removedSign: "#ff5555",
        lineNumber: "#989aa4",
        addedLineNumberBg: "#1a3a1a",
        removedLineNumberBg: "#3a1a1a",
    },
    markdown: {
        heading: "#bd93f9",
        code: "#50fa7b",
        link: "#8be9fd",
        linkText: "#ff79c6",
        quote: "#6272a4",
        bullet: "#bd93f9",
        rule: "#6272a4",
        strong: "#ffb86c",
        emphasis: "#f1fa8c",
        strikethrough: "#6272a4",
    },
    syntax: {
        keyword: "#ff79c6",
        string: "#f1fa8c",
        comment: "#6272a4",
        function: "#50fa7b",
        type: "#8be9fd",
        number: "#bd93f9",
        operator: "#ff79c6",
        punctuation: "#f8f8f2",
        variable: "#f8f8f2",
        variableBuiltin: "#f8f8f2",
        label: "#f1fa8c",
    },
};
