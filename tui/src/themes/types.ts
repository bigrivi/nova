/** Shared theme type. */
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

