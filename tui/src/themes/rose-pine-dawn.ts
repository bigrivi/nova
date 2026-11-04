/** Rose Pine Dawn theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const rosePineDawnTheme: Theme = {
    background: {
        base: "#faf4ed",
        raised: "#ddd7d8",
    },
    text: {
        base: "#575279",
        muted: "#6f6a8a",
        faint: "#9b96aa",
    },
    primary: {
        base: "#44757e",
        foreground: "#faf4ed",
        muted: "#44757e",
    },
    border: {
        base: "#c9c3ca",
    },
    feedback: {
        success: "#286983",
        error: "#ad546d",
        running: "#9e6210",
    },
    diff: {
        addedBg: "#d8dedc",
        removedBg: "#eedad9",
        contextBg: "#f2ece7",
        addedSign: "#286983",
        removedSign: "#ad546d",
        lineNumber: "#6f6a8a",
        addedLineNumberBg: "#d8dedc",
        removedLineNumberBg: "#eedad9",
    },
    markdown: {
        heading: "#44757e",
        code: "#286983",
        link: "#44757e",
        linkText: "#cc605b",
        quote: "#9b96aa",
        bullet: "#44757e",
        rule: "#9d96a9",
        strong: "#9e6210",
        emphasis: "#8f78a8",
        strikethrough: "#9b96aa",
    },
    syntax: {
        keyword: "#8f78a8",
        string: "#286983",
        comment: "#9893a5",
        function: "#44757e",
        type: "#cc605b",
        number: "#8f78a8",
        operator: "#8f78a8",
        punctuation: "#575279",
        variable: "#575279",
        variableBuiltin: "#9e6210",
        label: "#9e6210",
    },
};
