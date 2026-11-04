/** Gruvbox Dark theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const gruvboxDarkTheme: Theme = {
    background: {
        base: "#282828",
        raised: "#3d3c37",
    },
    text: {
        base: "#ebdbb2",
        muted: "#999078",
        faint: "#6c6758",
    },
    primary: {
        base: "#519ca0",
        foreground: "#282828",
        muted: "#519ca0",
    },
    border: {
        base: "#635e51",
    },
    feedback: {
        success: "#98971a",
        error: "#e8655f",
        running: "#d79921",
    },
    diff: {
        addedBg: "#3a3a26",
        removedBg: "#473231",
        contextBg: "#32312f",
        addedSign: "#98971a",
        removedSign: "#e8655f",
        lineNumber: "#999078",
        addedLineNumberBg: "#3a3a26",
        removedLineNumberBg: "#473231",
    },
    markdown: {
        heading: "#519ca0",
        code: "#98971a",
        link: "#519ca0",
        linkText: "#689d6a",
        quote: "#6c6758",
        bullet: "#519ca0",
        rule: "#8a826d",
        strong: "#d79921",
        emphasis: "#b26487",
        strikethrough: "#6c6758",
    },
    syntax: {
        keyword: "#b26487",
        string: "#98971a",
        comment: "#928374",
        function: "#519ca0",
        type: "#689d6a",
        number: "#b26487",
        operator: "#b26487",
        punctuation: "#ebdbb2",
        variable: "#ebdbb2",
        variableBuiltin: "#d79921",
        label: "#d79921",
    },
};
