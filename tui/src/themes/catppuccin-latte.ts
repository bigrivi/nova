/** Catppuccin Latte theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const catppuccinLatteTheme: Theme = {
    background: {
        base: "#eff1f5",
        raised: "#d2d4dc",
    },
    text: {
        base: "#4c4f69",
        muted: "#686b81",
        faint: "#9295a5",
    },
    primary: {
        base: "#145ff5",
        foreground: "#eff1f5",
        muted: "#145ff5",
    },
    border: {
        base: "#bec0cb",
    },
    feedback: {
        success: "#327c21",
        error: "#d20f39",
        running: "#996114",
    },
    diff: {
        addedBg: "#d1ded3",
        removedBg: "#eacdd7",
        contextBg: "#e7e9ee",
        addedSign: "#327c21",
        removedSign: "#d20f39",
        lineNumber: "#686b81",
        addedLineNumberBg: "#d1ded3",
        removedLineNumberBg: "#eacdd7",
    },
    markdown: {
        heading: "#145ff5",
        code: "#327c21",
        link: "#145ff5",
        linkText: "#168c92",
        quote: "#9295a5",
        bullet: "#145ff5",
        rule: "#9395a6",
        strong: "#996114",
        emphasis: "#e034b2",
        strikethrough: "#9295a5",
    },
    syntax: {
        keyword: "#e034b2",
        string: "#327c21",
        comment: "#9196a9",
        function: "#145ff5",
        type: "#168c92",
        number: "#e034b2",
        operator: "#e034b2",
        punctuation: "#4c4f69",
        variable: "#4c4f69",
        variableBuiltin: "#996114",
        label: "#996114",
    },
};
