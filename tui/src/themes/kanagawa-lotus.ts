/** Kanagawa Lotus theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const kanagawaLotusTheme: Theme = {
    background: {
        base: "#f2ecbc",
        raised: "#d4cfab",
    },
    text: {
        base: "#545464",
        muted: "#67666f",
        faint: "#939187",
    },
    primary: {
        base: "#4c6899",
        foreground: "#f2ecbc",
        muted: "#4c6899",
    },
    border: {
        base: "#c3bea2",
    },
    feedback: {
        success: "#5b7140",
        error: "#bf374a",
        running: "#706b3b",
    },
    diff: {
        addedBg: "#dad8a8",
        removedBg: "#eacfaa",
        contextBg: "#eae4b8",
        addedSign: "#5b7140",
        removedSign: "#bf374a",
        lineNumber: "#67666f",
        addedLineNumberBg: "#dad8a8",
        removedLineNumberBg: "#eacfaa",
    },
    markdown: {
        heading: "#4c6899",
        code: "#5b7140",
        link: "#4c6899",
        linkText: "#597b75",
        quote: "#939187",
        bullet: "#4c6899",
        rule: "#95927f",
        strong: "#706b3b",
        emphasis: "#b35b79",
        strikethrough: "#939187",
    },
    syntax: {
        keyword: "#b35b79",
        string: "#5b7140",
        comment: "#8a8980",
        function: "#4c6899",
        type: "#597b75",
        number: "#b35b79",
        operator: "#b35b79",
        punctuation: "#545464",
        variable: "#545464",
        variableBuiltin: "#706b3b",
        label: "#706b3b",
    },
};
