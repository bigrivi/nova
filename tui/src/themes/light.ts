/** Light theme (palette aligned with OpenCode). */
import type { Theme } from "./types.ts";

export const lightTheme: Theme = {
    background: {
        base: "#ffffff",
        raised: "#f6f8fa",
    },
    text: {
        base: "#24292f",
        muted: "#505459",
        faint: "#57606a",
    },
    primary: {
        base: "#0969da",
        foreground: "#ffffff",
        muted: "#0969da",
    },
    border: {
        base: "#d0d7de",
    },
    feedback: {
        running: "#9a6700",
        success: "#1a7f37",
        error: "#cf222e",
    },
    diff: {
        addedBg: "#dafbe1",
        removedBg: "#ffebe9",
        contextBg: "#f6f8fa",
        addedSign: "#1a7f37",
        removedSign: "#cf222e",
        lineNumber: "#57606a",
        addedLineNumberBg: "#dafbe1",
        removedLineNumberBg: "#ffebe9",
    },
    markdown: {
        heading: "#0969da",
        code: "#bf3989",
        link: "#0969da",
        linkText: "#1b7c83",
        quote: "#57606a",
        bullet: "#0969da",
        rule: "#d0d7de",
        strong: "#bc4c00",
        emphasis: "#9a6700",
        strikethrough: "#57606a",
    },
    syntax: {
        keyword: "#cf222e",
        string: "#0969da",
        comment: "#57606a",
        function: "#8250df",
        type: "#bc4c00",
        number: "#1b7c83",
        operator: "#cf222e",
        punctuation: "#24292f",
        variable: "#bc4c00",
        variableBuiltin: "#bc4c00",
        label: "#0969da",
    },
};
