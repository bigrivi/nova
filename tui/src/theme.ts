/** Semantic color tokens for the whole TUI. Multiple named themes are provided;
 *  components read the active one through useTheme(). */

export type Theme = {
    background: string;
    foreground: string;
    muted: string;
    subtle: string;
    accent: string;
    running: string;
    success: string;
    error: string;
    surface: string;
    surfaceDeep: string;
    border: string;
    diff: {
        addedBg: string;
        removedBg: string;
        contextBg: string;
        addedSign: string;
        removedSign: string;
        lineNumber: string;
        lineNumberBg: string;
        addedLineNumberBg: string;
        removedLineNumberBg: string;
    };
    heading: string;
    codeInline: string;
    link: string;
    linkUrl: string;
    quote: string;
    bullet: string;
    rule: string;
    strong: string;
    italic: string;
    strikethrough: string;
    syntaxKeyword: string;
    syntaxString: string;
    syntaxComment: string;
    syntaxFunction: string;
    syntaxType: string;
    syntaxNumber: string;
    syntaxOperator: string;
    syntaxPunctuation: string;
    syntaxVariable: string;
    syntaxVariableBuiltin: string;
    syntaxLabel: string;
};

export const darkTheme: Theme = {
    background: "#0d1117",
    foreground: "#e6edf3",
    muted: "#6e7681",
    subtle: "#8b949e",
    accent: "#4f9cf9",
    running: "#d29922",
    success: "#3fb950",
    error: "#e5534b",
    surface: "#161616",
    surfaceDeep: "#0d1117",
    border: "#30363d",
    diff: {
        addedBg: "#162a1a",
        removedBg: "#2a1616",
        contextBg: "#161616",
        addedSign: "#3fb950",
        removedSign: "#e5534b",
        lineNumber: "#6e7681",
        lineNumberBg: "#161616",
        addedLineNumberBg: "#162a1a",
        removedLineNumberBg: "#2a1616",
    },
    heading: "#79c0ff",
    codeInline: "#d2a8ff",
    link: "#4f9cf9",
    linkUrl: "#8b949e",
    quote: "#8b949e",
    bullet: "#79c0ff",
    rule: "#484f58",
    strong: "#ffa657",
    italic: "#d2a8ff",
    strikethrough: "#8b949e",
    syntaxKeyword: "#ff7b72",
    syntaxString: "#a5d6ff",
    syntaxComment: "#8b949e",
    syntaxFunction: "#d2a8ff",
    syntaxType: "#ffa657",
    syntaxNumber: "#79c0ff",
    syntaxOperator: "#ff7b72",
    syntaxPunctuation: "#c9d1d9",
    syntaxVariable: "#e6edf3",
    syntaxVariableBuiltin: "#e6edf3",
    syntaxLabel: "#a5d6ff",
};

export const lightTheme: Theme = {
    background: "#f6f8fa",
    foreground: "#1f2328",
    muted: "#656d76",
    subtle: "#57606a",
    accent: "#0969da",
    running: "#9a6700",
    success: "#1a7f37",
    error: "#cf222e",
    surface: "#eaeef2",
    surfaceDeep: "#f6f8fa",
    border: "#d0d7de",
    diff: {
        addedBg: "#e6ffec",
        removedBg: "#ffebe9",
        contextBg: "#f6f8fa",
        addedSign: "#1a7f37",
        removedSign: "#cf222e",
        lineNumber: "#656d76",
        lineNumberBg: "#f6f8fa",
        addedLineNumberBg: "#ccffd8",
        removedLineNumberBg: "#ffd7d5",
    },
    heading: "#0550ae",
    codeInline: "#8250df",
    link: "#0969da",
    linkUrl: "#57606a",
    quote: "#57606a",
    bullet: "#0550ae",
    rule: "#d0d7de",
    strong: "#953800",
    italic: "#8250df",
    strikethrough: "#57606a",
    syntaxKeyword: "#cf222e",
    syntaxString: "#0a3069",
    syntaxComment: "#6e7781",
    syntaxFunction: "#8250df",
    syntaxType: "#953800",
    syntaxNumber: "#0550ae",
    syntaxOperator: "#cf222e",
    syntaxPunctuation: "#24292f",
    syntaxVariable: "#24292f",
    syntaxVariableBuiltin: "#24292f",
    syntaxLabel: "#0a3069",
};

export const palenightTheme: Theme = {
    background: "#292d3e",
    foreground: "#a6accd",
    muted: "#676e95",
    subtle: "#8796b0",
    accent: "#82aaff",
    running: "#ffcb6b",
    success: "#c3e88d",
    error: "#ff5370",
    surface: "#32374d",
    surfaceDeep: "#292d3e",
    border: "#444267",
    diff: {
        addedBg: "#304230",
        removedBg: "#422b2b",
        contextBg: "#292d3e",
        addedSign: "#c3e88d",
        removedSign: "#ff5370",
        lineNumber: "#676e95",
        lineNumberBg: "#292d3e",
        addedLineNumberBg: "#304230",
        removedLineNumberBg: "#422b2b",
    },
    heading: "#82aaff",
    codeInline: "#c792ea",
    link: "#82aaff",
    linkUrl: "#8796b0",
    quote: "#8796b0",
    bullet: "#82aaff",
    rule: "#444267",
    strong: "#ffcb6b",
    italic: "#c792ea",
    strikethrough: "#8796b0",
    syntaxKeyword: "#c792ea",
    syntaxString: "#c3e88d",
    syntaxComment: "#676e95",
    syntaxFunction: "#82aaff",
    syntaxType: "#ffcb6b",
    syntaxNumber: "#f78c6c",
    syntaxOperator: "#89ddff",
    syntaxPunctuation: "#a6accd",
    syntaxVariable: "#a6accd",
    syntaxVariableBuiltin: "#a6accd",
    syntaxLabel: "#c3e88d",
};

export const draculaTheme: Theme = {
    background: "#282a36",
    foreground: "#f8f8f2",
    muted: "#6272a4",
    subtle: "#8b95a7",
    accent: "#bd93f9",
    running: "#ffb86c",
    success: "#50fa7b",
    error: "#ff5555",
    surface: "#343746",
    surfaceDeep: "#282a36",
    border: "#44475a",
    diff: {
        addedBg: "#2d3a2d",
        removedBg: "#3a2d2d",
        contextBg: "#282a36",
        addedSign: "#50fa7b",
        removedSign: "#ff5555",
        lineNumber: "#6272a4",
        lineNumberBg: "#282a36",
        addedLineNumberBg: "#2d3a2d",
        removedLineNumberBg: "#3a2d2d",
    },
    heading: "#8be9fd",
    codeInline: "#ff79c6",
    link: "#8be9fd",
    linkUrl: "#8b95a7",
    quote: "#8b95a7",
    bullet: "#bd93f9",
    rule: "#44475a",
    strong: "#ffb86c",
    italic: "#ff79c6",
    strikethrough: "#8b95a7",
    syntaxKeyword: "#ff79c6",
    syntaxString: "#f1fa8c",
    syntaxComment: "#6272a4",
    syntaxFunction: "#50fa7b",
    syntaxType: "#8be9fd",
    syntaxNumber: "#bd93f9",
    syntaxOperator: "#ff79c6",
    syntaxPunctuation: "#f8f8f2",
    syntaxVariable: "#f8f8f2",
    syntaxVariableBuiltin: "#f8f8f2",
    syntaxLabel: "#f1fa8c",
};

export const themes: Record<string, Theme> = {
    dark: darkTheme,
    light: lightTheme,
    palenight: palenightTheme,
    dracula: draculaTheme,
};

export const themeNames = Object.keys(themes);

export const theme = darkTheme;
export const darkThemeTokens = darkTheme;
