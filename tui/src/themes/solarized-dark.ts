/** Solarized Dark theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const solarizedDarkTheme: Theme = {
    background: {
        base: "#002b36",
        raised: "#183f48",
    },
    text: {
        base: "#99a7a9",
        muted: "#7f9295",
        faint: "#506b72",
    },
    primary: {
        base: "#3295da",
        foreground: "#002b36",
        muted: "#3295da",
    },
    border: {
        base: "#2e5059",
    },
    feedback: {
        success: "#859900",
        error: "#e56663",
        running: "#b58900",
    },
    diff: {
        addedBg: "#153d2d",
        removedBg: "#25343d",
        contextBg: "#08313c",
        addedSign: "#859900",
        removedSign: "#e56663",
        lineNumber: "#7f9295",
        addedLineNumberBg: "#153d2d",
        removedLineNumberBg: "#25343d",
    },
    markdown: {
        heading: "#3295da",
        code: "#859900",
        link: "#3295da",
        linkText: "#2aa198",
        quote: "#506b72",
        bullet: "#3295da",
        rule: "#4f6c73",
        strong: "#b58900",
        emphasis: "#d54089",
        strikethrough: "#506b72",
    },
    syntax: {
        keyword: "#d54089",
        string: "#859900",
        comment: "#00708d",
        function: "#3295da",
        type: "#2aa198",
        number: "#d54089",
        operator: "#d54089",
        punctuation: "#99a7a9",
        variable: "#99a7a9",
        variableBuiltin: "#b58900",
        label: "#b58900",
    },
};
