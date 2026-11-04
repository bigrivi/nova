/** TokyoNight Day theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const tokyoNightDayTheme: Theme = {
    background: {
        base: "#e1e2e7",
        raised: "#c1c7d9",
    },
    text: {
        base: "#2d4e9b",
        muted: "#4461a5",
        faint: "#778bba",
    },
    primary: {
        base: "#155fc5",
        foreground: "#e1e2e7",
        muted: "#155fc5",
    },
    border: {
        base: "#abb6d0",
    },
    feedback: {
        success: "#526c35",
        error: "#c90941",
        running: "#7c6037",
    },
    diff: {
        addedBg: "#cacfcb",
        removedBg: "#ddbfcc",
        contextBg: "#d8dbe3",
        addedSign: "#526c35",
        removedSign: "#c90941",
        lineNumber: "#4461a5",
        addedLineNumberBg: "#cacfcb",
        removedLineNumberBg: "#ddbfcc",
    },
    markdown: {
        heading: "#155fc5",
        code: "#526c35",
        link: "#155fc5",
        linkText: "#007197",
        quote: "#778bba",
        bullet: "#155fc5",
        rule: "#788bb9",
        strong: "#7c6037",
        emphasis: "#944df0",
        strikethrough: "#778bba",
    },
    syntax: {
        keyword: "#944df0",
        string: "#526c35",
        comment: "#8188b2",
        function: "#155fc5",
        type: "#007197",
        number: "#944df0",
        operator: "#944df0",
        punctuation: "#2d4e9b",
        variable: "#2d4e9b",
        variableBuiltin: "#7c6037",
        label: "#7c6037",
    },
};
