/** Palenight light theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const palenightLightTheme: Theme = {
    background: {
        base: "#fafafa",
        raised: "#f5f5f5",
    },
    text: {
        base: "#292d3e",
        muted: "#484c5a",
        faint: "#8796b0",
    },
    primary: {
        base: "#4976eb",
        foreground: "#000000",
        muted: "#446bd1",
    },
    border: {
        base: "#e0e0e0",
    },
    feedback: {
        running: "#ffb300",
        success: "#91b859",
        error: "#e53935",
    },
    diff: {
        addedBg: "#e8f5e9",
        removedBg: "#ffebee",
        contextBg: "#f5f5f5",
        addedSign: "#91b859",
        removedSign: "#e53935",
        lineNumber: "#6a6e70",
        addedLineNumberBg: "#e8f5e9",
        removedLineNumberBg: "#ffebee",
    },
    markdown: {
        heading: "#a854f2",
        code: "#91b859",
        link: "#4976eb",
        linkText: "#00acc1",
        quote: "#8796b0",
        bullet: "#4976eb",
        rule: "#8796b0",
        strong: "#f4511e",
        emphasis: "#ffb300",
        strikethrough: "#8796b0",
    },
    syntax: {
        keyword: "#a854f2",
        string: "#91b859",
        comment: "#8796b0",
        function: "#4976eb",
        type: "#ffb300",
        number: "#f4511e",
        operator: "#00acc1",
        punctuation: "#292d3e",
        variable: "#292d3e",
        variableBuiltin: "#292d3e",
        label: "#91b859",
    },
};
