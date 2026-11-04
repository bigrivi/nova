/** Rose Pine Moon theme (palette from the iTerm2-Color-Schemes collection). */
import type { Theme } from "./types.ts";

export const rosePineTheme: Theme = {
    background: {
        base: "#232136",
        raised: "#38364b",
    },
    text: {
        base: "#e0def4",
        muted: "#8d8ba0",
        faint: "#636177",
    },
    primary: {
        base: "#9ccfd8",
        foreground: "#232136",
        muted: "#9ccfd8",
    },
    border: {
        base: "#5c5a6f",
    },
    feedback: {
        success: "#4094b6",
        error: "#eb6f92",
        running: "#f6c177",
    },
    diff: {
        addedBg: "#28334a",
        removedBg: "#432d45",
        contextBg: "#2c2a40",
        addedSign: "#4094b6",
        removedSign: "#eb6f92",
        lineNumber: "#8d8ba0",
        addedLineNumberBg: "#28334a",
        removedLineNumberBg: "#432d45",
    },
    markdown: {
        heading: "#9ccfd8",
        code: "#4094b6",
        link: "#9ccfd8",
        linkText: "#ea9a97",
        quote: "#636177",
        bullet: "#9ccfd8",
        rule: "#828095",
        strong: "#f6c177",
        emphasis: "#c4a7e7",
        strikethrough: "#636177",
    },
    syntax: {
        keyword: "#c4a7e7",
        string: "#4094b6",
        comment: "#6e6a86",
        function: "#9ccfd8",
        type: "#ea9a97",
        number: "#c4a7e7",
        operator: "#c4a7e7",
        punctuation: "#e0def4",
        variable: "#e0def4",
        variableBuiltin: "#f6c177",
        label: "#f6c177",
    },
};
