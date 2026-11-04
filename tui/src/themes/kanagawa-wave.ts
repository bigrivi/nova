/** Kanagawa Wave theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const kanagawaWaveTheme: Theme = {
    background: {
        base: "#1f1f28",
        raised: "#343338",
    },
    text: {
        base: "#dcd7ba",
        muted: "#8d8a7d",
        faint: "#63615d",
    },
    primary: {
        base: "#7e9cd8",
        foreground: "#1f1f28",
        muted: "#7e9cd8",
    },
    border: {
        base: "#585654",
    },
    feedback: {
        success: "#76946a",
        error: "#cf6769",
        running: "#c0a36e",
    },
    diff: {
        addedBg: "#2d3233",
        removedBg: "#3b2b32",
        contextBg: "#28282f",
        addedSign: "#76946a",
        removedSign: "#cf6769",
        lineNumber: "#8d8a7d",
        addedLineNumberBg: "#2d3233",
        removedLineNumberBg: "#3b2b32",
    },
    markdown: {
        heading: "#7e9cd8",
        code: "#76946a",
        link: "#7e9cd8",
        linkText: "#6a9589",
        quote: "#63615d",
        bullet: "#7e9cd8",
        rule: "#7e7b71",
        strong: "#c0a36e",
        emphasis: "#957fb8",
        strikethrough: "#63615d",
    },
    syntax: {
        keyword: "#957fb8",
        string: "#76946a",
        comment: "#727169",
        function: "#7e9cd8",
        type: "#6a9589",
        number: "#957fb8",
        operator: "#957fb8",
        punctuation: "#dcd7ba",
        variable: "#dcd7ba",
        variableBuiltin: "#c0a36e",
        label: "#c0a36e",
    },
};
