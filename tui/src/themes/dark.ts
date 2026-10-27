/** Dark theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const darkTheme: Theme = {
    background: {
        base: "#0d1117",
        raised: "#010409",
    },
    text: {
        base: "#c9d1d9",
        muted: "#9aa1a9",
        faint: "#8b949e",
    },
    primary: {
        base: "#58a6ff",
        foreground: "#0d1117",
        muted: "#58a6ff",
    },
    border: {
        base: "#30363d",
    },
    feedback: {
        running: "#e3b341",
        success: "#3fb950",
        error: "#f85149",
    },
    diff: {
        addedBg: "#033a16",
        removedBg: "#67060c",
        contextBg: "#010409",
        addedSign: "#3fb950",
        removedSign: "#f85149",
        lineNumber: "#95999e",
        addedLineNumberBg: "#033a16",
        removedLineNumberBg: "#67060c",
    },
    markdown: {
        heading: "#58a6ff",
        code: "#ff7b72",
        link: "#58a6ff",
        linkText: "#39c5cf",
        quote: "#8b949e",
        bullet: "#58a6ff",
        rule: "#30363d",
        strong: "#d29922",
        emphasis: "#e3b341",
        strikethrough: "#8b949e",
    },
    syntax: {
        keyword: "#ff7b72",
        string: "#39c5cf",
        comment: "#8b949e",
        function: "#bc8cff",
        type: "#d29922",
        number: "#58a6ff",
        operator: "#ff7b72",
        punctuation: "#c9d1d9",
        variable: "#d29922",
        variableBuiltin: "#d29922",
        label: "#39c5cf",
    },
};
