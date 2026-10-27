/** Palenight theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const palenightTheme: Theme = {
    background: {
        base: "#292d3e",
        raised: "#1e2132",
    },
    text: {
        base: "#a6accd",
        muted: "#a6accd",
        faint: "#676e95",
    },
    primary: {
        base: "#82aaff",
        foreground: "#292d3e",
        muted: "#82aaff",
    },
    border: {
        base: "#32364a",
    },
    feedback: {
        running: "#ffcb6b",
        success: "#c3e88d",
        error: "#f07178",
    },
    diff: {
        addedBg: "#2e3c2b",
        removedBg: "#3c2b2b",
        contextBg: "#1e2132",
        addedSign: "#c3e88d",
        removedSign: "#f07178",
        lineNumber: "#a0a2af",
        addedLineNumberBg: "#2e3c2b",
        removedLineNumberBg: "#3c2b2b",
    },
    markdown: {
        heading: "#c792ea",
        code: "#c3e88d",
        link: "#82aaff",
        linkText: "#89ddff",
        quote: "#676e95",
        bullet: "#82aaff",
        rule: "#676e95",
        strong: "#f78c6c",
        emphasis: "#ffcb6b",
        strikethrough: "#676e95",
    },
    syntax: {
        keyword: "#c792ea",
        string: "#c3e88d",
        comment: "#676e95",
        function: "#82aaff",
        type: "#ffcb6b",
        number: "#f78c6c",
        operator: "#89ddff",
        punctuation: "#a6accd",
        variable: "#a6accd",
        variableBuiltin: "#a6accd",
        label: "#c3e88d",
    },
};
