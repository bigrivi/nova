import { SyntaxStyle, getTreeSitterClient } from "@opentui/core";
import { useMemo } from "react";
import { useTheme } from "../../context/theme.tsx";
import type { Theme } from "../../themes/index.ts";

export function buildSyntaxStyles(theme: Theme) {
    return {
    default: { fg: theme.text.base },
    conceal: { fg: theme.text.muted },

    "markup.heading": { fg: theme.markdown.heading, bold: true },
    "markup.heading.1": { fg: theme.markdown.heading, bold: true },
    "markup.heading.2": { fg: theme.markdown.heading, bold: true },
    "markup.heading.3": { fg: theme.markdown.heading, bold: true },
    "markup.heading.4": { fg: theme.markdown.heading, bold: true },
    "markup.heading.5": { fg: theme.markdown.heading, bold: true },
    "markup.heading.6": { fg: theme.markdown.heading, bold: true },

    "markup.raw": { fg: theme.markdown.code },
    "markup.raw.block": { fg: theme.syntax.comment },
    "markup.strong": { fg: theme.markdown.strong, bold: true },
    "markup.italic": { fg: theme.markdown.emphasis, italic: true },
    "markup.strikethrough": { fg: theme.markdown.strikethrough },

    "markup.link": { fg: theme.markdown.link, underline: true },
    "markup.link.label": { fg: theme.markdown.link, underline: true },
    "markup.link.url": { fg: theme.markdown.linkText, underline: true },
    label: { fg: theme.syntax.label },
    "string.escape": { fg: theme.syntax.comment },
    "keyword.directive": { fg: theme.syntax.keyword },
    "character.special": { fg: theme.syntax.string },
    "punctuation.special": { fg: theme.markdown.rule },

    "markup.list": { fg: theme.markdown.bullet, bold: true },
    "markup.list.checked": { fg: theme.markdown.bullet },
    "markup.list.unchecked": { fg: theme.markdown.bullet },
    "markup.quote": { fg: theme.markdown.quote, italic: true },

    keyword: { fg: theme.syntax.keyword },
    string: { fg: theme.syntax.string },
    comment: { fg: theme.syntax.comment },
    function: { fg: theme.syntax.function },
    type: { fg: theme.syntax.type },
    "type.builtin": { fg: theme.syntax.type },
    number: { fg: theme.syntax.number },
    boolean: { fg: theme.syntax.number },
    constant: { fg: theme.syntax.number },
    property: { fg: theme.syntax.number },
    operator: { fg: theme.syntax.operator },
    punctuation: { fg: theme.syntax.punctuation },
    variable: { fg: theme.syntax.variable },
    parameter: { fg: theme.syntax.variableBuiltin },
} as const;
}

export function MarkdownPart({
    text,
    streaming,
}: {
    text: string;
    streaming: boolean;
}) {
    const theme = useTheme();
    const syntaxStyle = useMemo(() => SyntaxStyle.fromStyles(buildSyntaxStyles(theme)), [theme]);
    const treeSitterClient = useMemo(() => getTreeSitterClient(), []);
    return (
        <markdown
            content={text}
            streaming={streaming}
            syntaxStyle={syntaxStyle}
            treeSitterClient={treeSitterClient}
            conceal
        />
    );
}
