/** Matrix light theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const matrixLightTheme: Theme = {
    background: {
        base: "#eef3ea",
        raised: "#ccd5ca",
    },
    text: {
        base: "#203022",
        muted: "#3f4d40",
        faint: "#748476",
    },
    primary: {
        base: "#1cc24b",
        foreground: "#203022",
        muted: "#1e7937",
    },
    border: {
        base: "#748476",
    },
    feedback: {
        running: "#e6ff57",
        success: "#1cc24b",
        error: "#ff4b4b",
    },
    diff: {
        addedBg: "#e0efde",
        removedBg: "#f9e5e5",
        contextBg: "#e4ebe1",
        addedSign: "#1cc24b",
        removedSign: "#ff4b4b",
        lineNumber: "#556156",
        addedLineNumberBg: "#d6e7d2",
        removedLineNumberBg: "#f2d2d2",
    },
    markdown: {
        heading: "#24f6d9",
        code: "#1cc24b",
        link: "#30b3ff",
        linkText: "#24f6d9",
        quote: "#748476",
        bullet: "#30b3ff",
        rule: "#748476",
        strong: "#e6ff57",
        emphasis: "#ffa83d",
        strikethrough: "#748476",
    },
    syntax: {
        keyword: "#c770ff",
        string: "#1cc24b",
        comment: "#748476",
        function: "#30b3ff",
        type: "#e6ff57",
        number: "#ffa83d",
        operator: "#24f6d9",
        punctuation: "#203022",
        variable: "#203022",
        variableBuiltin: "#203022",
        label: "#1cc24b",
    },
};
