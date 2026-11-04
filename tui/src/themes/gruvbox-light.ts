/** Gruvbox Light theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const gruvboxLightTheme: Theme = {
    background: {
        base: "#fbf1c7",
        raised: "#dcd3b0",
    },
    text: {
        base: "#3c3836",
        muted: "#716c5f",
        faint: "#9d9680",
    },
    primary: {
        base: "#3c7477",
        foreground: "#fbf1c7",
        muted: "#3c7477",
    },
    border: {
        base: "#c2ba9c",
    },
    feedback: {
        success: "#717013",
        error: "#cc241d",
        running: "#8e6516",
    },
    diff: {
        addedBg: "#e5dcaa",
        removedBg: "#f3d0ac",
        contextBg: "#f1e8c0",
        addedSign: "#717013",
        removedSign: "#cc241d",
        lineNumber: "#716c5f",
        addedLineNumberBg: "#e5dcaa",
        removedLineNumberBg: "#f3d0ac",
    },
    markdown: {
        heading: "#3c7477",
        code: "#717013",
        link: "#3c7477",
        linkText: "#5a8a5c",
        quote: "#9d9680",
        bullet: "#3c7477",
        rule: "#9c957f",
        strong: "#8e6516",
        emphasis: "#b16286",
        strikethrough: "#9d9680",
    },
    syntax: {
        keyword: "#b16286",
        string: "#717013",
        comment: "#928374",
        function: "#3c7477",
        type: "#5a8a5c",
        number: "#b16286",
        operator: "#b16286",
        punctuation: "#3c3836",
        variable: "#3c3836",
        variableBuiltin: "#8e6516",
        label: "#8e6516",
    },
};
