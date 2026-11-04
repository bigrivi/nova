/** Everforest Light Med theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const everforestLightTheme: Theme = {
    background: {
        base: "#efebd4",
        raised: "#d0cfbe",
    },
    text: {
        base: "#4d5960",
        muted: "#5f696d",
        faint: "#8e938e",
    },
    primary: {
        base: "#3c716a",
        foreground: "#efebd4",
        muted: "#3c716a",
    },
    border: {
        base: "#bebfb1",
    },
    feedback: {
        success: "#5b7138",
        error: "#ca272a",
        running: "#856525",
    },
    diff: {
        addedBg: "#d7d7bb",
        removedBg: "#e9ccb9",
        contextBg: "#e7e4ce",
        addedSign: "#5b7138",
        removedSign: "#ca272a",
        lineNumber: "#5f696d",
        addedLineNumberBg: "#d7d7bb",
        removedLineNumberBg: "#e9ccb9",
    },
    markdown: {
        heading: "#3c716a",
        code: "#5b7138",
        link: "#3c716a",
        linkText: "#458856",
        quote: "#8e938e",
        bullet: "#3c716a",
        rule: "#8f938a",
        strong: "#856525",
        emphasis: "#bc5988",
        strikethrough: "#8e938e",
    },
    syntax: {
        keyword: "#bc5988",
        string: "#5b7138",
        comment: "#889580",
        function: "#3c716a",
        type: "#458856",
        number: "#bc5988",
        operator: "#bc5988",
        punctuation: "#4d5960",
        variable: "#4d5960",
        variableBuiltin: "#856525",
        label: "#856525",
    },
};
