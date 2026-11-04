/** Everforest Dark Med theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const everforestDarkTheme: Theme = {
    background: {
        base: "#232a2e",
        raised: "#383d3d",
    },
    text: {
        base: "#d3c6aa",
        muted: "#979180",
        faint: "#696860",
    },
    primary: {
        base: "#7fbbb3",
        foreground: "#232a2e",
        muted: "#7fbbb3",
    },
    border: {
        base: "#585953",
    },
    feedback: {
        success: "#a7c080",
        error: "#e67e80",
        running: "#dbbc7f",
    },
    diff: {
        addedBg: "#38423b",
        removedBg: "#42373b",
        contextBg: "#2c3234",
        addedSign: "#a7c080",
        removedSign: "#e67e80",
        lineNumber: "#979180",
        addedLineNumberBg: "#38423b",
        removedLineNumberBg: "#42373b",
    },
    markdown: {
        heading: "#7fbbb3",
        code: "#a7c080",
        link: "#7fbbb3",
        linkText: "#83c092",
        quote: "#696860",
        bullet: "#7fbbb3",
        rule: "#7b786c",
        strong: "#dbbc7f",
        emphasis: "#d699b6",
        strikethrough: "#696860",
    },
    syntax: {
        keyword: "#d699b6",
        string: "#a7c080",
        comment: "#a6b0a0",
        function: "#7fbbb3",
        type: "#83c092",
        number: "#d699b6",
        operator: "#d699b6",
        punctuation: "#d3c6aa",
        variable: "#d3c6aa",
        variableBuiltin: "#dbbc7f",
        label: "#dbbc7f",
    },
};
