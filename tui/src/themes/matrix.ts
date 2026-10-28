/** Matrix theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const matrixTheme: Theme = {
    background: {
        base: "#0a0e0a",
        raised: "#182f1d",
    },
    text: {
        base: "#62ff94",
        muted: "#48b76b",
        faint: "#8ca391",
    },
    primary: {
        base: "#2eff6a",
        foreground: "#0a0e0a",
        muted: "#1cc24b",
    },
    border: {
        base: "#1e2a1b",
    },
    feedback: {
        running: "#e6ff57",
        success: "#62ff94",
        error: "#ff4b4b",
    },
    diff: {
        addedBg: "#132616",
        removedBg: "#261212",
        contextBg: "#0e130d",
        addedSign: "#62ff94",
        removedSign: "#ff4b4b",
        lineNumber: "#8ca391",
        addedLineNumberBg: "#0f1b11",
        removedLineNumberBg: "#1b1414",
    },
    markdown: {
        heading: "#00efff",
        code: "#1cc24b",
        link: "#30b3ff",
        linkText: "#24f6d9",
        quote: "#8ca391",
        bullet: "#30b3ff",
        rule: "#8ca391",
        strong: "#e6ff57",
        emphasis: "#ffa83d",
        strikethrough: "#8ca391",
    },
    syntax: {
        keyword: "#c770ff",
        string: "#1cc24b",
        comment: "#8ca391",
        function: "#30b3ff",
        type: "#e6ff57",
        number: "#ffa83d",
        operator: "#24f6d9",
        punctuation: "#62ff94",
        variable: "#62ff94",
        variableBuiltin: "#62ff94",
        label: "#1cc24b",
    },
};
