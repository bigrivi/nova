/** Nord theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const nordTheme: Theme = {
    background: {
        base: "#2e3440",
        raised: "#414753",
    },
    text: {
        base: "#d8dee9",
        muted: "#999faa",
        faint: "#6d737f",
    },
    primary: {
        base: "#81a1c1",
        foreground: "#2e3440",
        muted: "#81a1c1",
    },
    border: {
        base: "#616773",
    },
    feedback: {
        success: "#a3be8c",
        error: "#cf8990",
        running: "#ebcb8b",
    },
    diff: {
        addedBg: "#414a4c",
        removedBg: "#48424d",
        contextBg: "#373d48",
        addedSign: "#a3be8c",
        removedSign: "#cf8990",
        lineNumber: "#999faa",
        addedLineNumberBg: "#414a4c",
        removedLineNumberBg: "#48424d",
    },
    markdown: {
        heading: "#81a1c1",
        code: "#a3be8c",
        link: "#81a1c1",
        linkText: "#88c0d0",
        quote: "#6d737f",
        bullet: "#81a1c1",
        rule: "#838995",
        strong: "#ebcb8b",
        emphasis: "#b48ead",
        strikethrough: "#6d737f",
    },
    syntax: {
        keyword: "#b48ead",
        string: "#a3be8c",
        comment: "#66738e",
        function: "#81a1c1",
        type: "#88c0d0",
        number: "#b48ead",
        operator: "#b48ead",
        punctuation: "#d8dee9",
        variable: "#d8dee9",
        variableBuiltin: "#ebcb8b",
        label: "#ebcb8b",
    },
};
