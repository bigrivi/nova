/** Solarized Light theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const solarizedLightTheme: Theme = {
    background: {
        base: "#fdf6e3",
        raised: "#dcdacb",
    },
    text: {
        base: "#4f6066",
        muted: "#647275",
        faint: "#959c98",
    },
    primary: {
        base: "#2074af",
        foreground: "#fdf6e3",
        muted: "#2074af",
    },
    border: {
        base: "#c9c9be",
    },
    feedback: {
        success: "#687800",
        error: "#da2825",
        running: "#8f6c00",
    },
    diff: {
        addedBg: "#e5e2bf",
        removedBg: "#f7d5c5",
        contextBg: "#f4efdd",
        addedSign: "#687800",
        removedSign: "#da2825",
        lineNumber: "#647275",
        addedLineNumberBg: "#e5e2bf",
        removedLineNumberBg: "#f7d5c5",
    },
    markdown: {
        heading: "#2074af",
        code: "#687800",
        link: "#2074af",
        linkText: "#269189",
        quote: "#959c98",
        bullet: "#2074af",
        rule: "#969c95",
        strong: "#8f6c00",
        emphasis: "#d33682",
        strikethrough: "#959c98",
    },
    syntax: {
        keyword: "#d33682",
        string: "#687800",
        comment: "#002b36",
        function: "#2074af",
        type: "#269189",
        number: "#d33682",
        operator: "#d33682",
        punctuation: "#4f6066",
        variable: "#4f6066",
        variableBuiltin: "#8f6c00",
        label: "#8f6c00",
    },
};
