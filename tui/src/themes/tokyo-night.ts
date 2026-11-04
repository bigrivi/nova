/** TokyoNight Storm theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const tokyoNightTheme: Theme = {
    background: {
        base: "#24283b",
        raised: "#373b51",
    },
    text: {
        base: "#c0caf5",
        muted: "#8890b2",
        faint: "#616784",
    },
    primary: {
        base: "#7aa2f7",
        foreground: "#24283b",
        muted: "#7aa2f7",
    },
    border: {
        base: "#535973",
    },
    feedback: {
        success: "#9ece6a",
        error: "#f7768e",
        running: "#e0af68",
    },
    diff: {
        addedBg: "#384343",
        removedBg: "#463448",
        contextBg: "#2c3044",
        addedSign: "#9ece6a",
        removedSign: "#f7768e",
        lineNumber: "#8890b2",
        addedLineNumberBg: "#384343",
        removedLineNumberBg: "#463448",
    },
    markdown: {
        heading: "#7aa2f7",
        code: "#9ece6a",
        link: "#7aa2f7",
        linkText: "#7dcfff",
        quote: "#616784",
        bullet: "#7aa2f7",
        rule: "#727998",
        strong: "#e0af68",
        emphasis: "#bb9af7",
        strikethrough: "#616784",
    },
    syntax: {
        keyword: "#bb9af7",
        string: "#9ece6a",
        comment: "#5c6694",
        function: "#7aa2f7",
        type: "#7dcfff",
        number: "#bb9af7",
        operator: "#bb9af7",
        punctuation: "#c0caf5",
        variable: "#c0caf5",
        variableBuiltin: "#e0af68",
        label: "#e0af68",
    },
};
