/** Catppuccin Mocha theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const catppuccinMochaTheme: Theme = {
    background: {
        base: "#1e1e2e",
        raised: "#313244",
    },
    text: {
        base: "#cdd6f4",
        muted: "#82879f",
        faint: "#5d6075",
    },
    primary: {
        base: "#89b4fa",
        foreground: "#1e1e2e",
        muted: "#89b4fa",
    },
    border: {
        base: "#535569",
    },
    feedback: {
        success: "#a6e3a1",
        error: "#f38ba8",
        running: "#f9e2af",
    },
    diff: {
        addedBg: "#343e40",
        removedBg: "#402f42",
        contextBg: "#272738",
        addedSign: "#a6e3a1",
        removedSign: "#f38ba8",
        lineNumber: "#82879f",
        addedLineNumberBg: "#343e40",
        removedLineNumberBg: "#402f42",
    },
    markdown: {
        heading: "#89b4fa",
        code: "#a6e3a1",
        link: "#89b4fa",
        linkText: "#94e2d5",
        quote: "#5d6075",
        bullet: "#89b4fa",
        rule: "#767a91",
        strong: "#f9e2af",
        emphasis: "#f5c2e7",
        strikethrough: "#5d6075",
    },
    syntax: {
        keyword: "#f5c2e7",
        string: "#a6e3a1",
        comment: "#5c6076",
        function: "#89b4fa",
        type: "#94e2d5",
        number: "#f5c2e7",
        operator: "#f5c2e7",
        punctuation: "#cdd6f4",
        variable: "#cdd6f4",
        variableBuiltin: "#f9e2af",
        label: "#f9e2af",
    },
};
