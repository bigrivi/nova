/** Nord Light theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const nordLightTheme: Theme = {
    background: {
        base: "#e5e9f0",
        raised: "#c7ccd5",
    },
    text: {
        base: "#414858",
        muted: "#606775",
        faint: "#8b909c",
    },
    primary: {
        base: "#466a8e",
        foreground: "#e5e9f0",
        muted: "#466a8e",
    },
    border: {
        base: "#b4b9c2",
    },
    feedback: {
        success: "#556f3f",
        error: "#ae4750",
        running: "#866117",
    },
    diff: {
        addedBg: "#ced5d4",
        removedBg: "#dccfd6",
        contextBg: "#dde1e8",
        addedSign: "#556f3f",
        removedSign: "#ae4750",
        lineNumber: "#606775",
        addedLineNumberBg: "#ced5d4",
        removedLineNumberBg: "#dccfd6",
    },
    markdown: {
        heading: "#466a8e",
        code: "#556f3f",
        link: "#466a8e",
        linkText: "#3c8398",
        quote: "#8b909c",
        bullet: "#466a8e",
        rule: "#89909c",
        strong: "#866117",
        emphasis: "#9c6992",
        strikethrough: "#8b909c",
    },
    syntax: {
        keyword: "#9c6992",
        string: "#556f3f",
        comment: "#4c566a",
        function: "#466a8e",
        type: "#3c8398",
        number: "#9c6992",
        operator: "#9c6992",
        punctuation: "#414858",
        variable: "#414858",
        variableBuiltin: "#866117",
        label: "#866117",
    },
};
