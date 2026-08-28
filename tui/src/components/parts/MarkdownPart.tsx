import { SyntaxStyle, getTreeSitterClient } from "@opentui/core";
import { useMemo } from "react";
import { theme } from "../../theme.ts";

const SYNTAX_STYLES = {
    default: { fg: theme.foreground },
    conceal: { fg: theme.muted },

    "markup.heading": { fg: theme.heading, bold: true },
    "markup.heading.1": { fg: theme.heading, bold: true },
    "markup.heading.2": { fg: theme.heading, bold: true },
    "markup.heading.3": { fg: theme.heading, bold: true },
    "markup.heading.4": { fg: theme.heading, bold: true },
    "markup.heading.5": { fg: theme.heading, bold: true },
    "markup.heading.6": { fg: theme.heading, bold: true },

    "markup.raw": { fg: theme.codeInline },
    "markup.raw.block": { fg: theme.syntaxComment },
    "markup.strong": { fg: theme.strong, bold: true },
    "markup.italic": { fg: theme.italic, italic: true },
    "markup.strikethrough": { fg: theme.strikethrough },

    "markup.link": { fg: theme.link, underline: true },
    "markup.link.label": { fg: theme.link, underline: true },
    "markup.link.url": { fg: theme.linkUrl, underline: true },
    label: { fg: theme.syntaxLabel },
    "string.escape": { fg: theme.syntaxComment },
    "keyword.directive": { fg: theme.syntaxKeyword },
    "character.special": { fg: theme.syntaxString },
    "punctuation.special": { fg: theme.rule },

    "markup.list": { fg: theme.bullet, bold: true },
    "markup.list.checked": { fg: theme.bullet },
    "markup.list.unchecked": { fg: theme.bullet },
    "markup.quote": { fg: theme.quote, italic: true },

    keyword: { fg: theme.syntaxKeyword },
    string: { fg: theme.syntaxString },
    comment: { fg: theme.syntaxComment },
    function: { fg: theme.syntaxFunction },
    type: { fg: theme.syntaxType },
    "type.builtin": { fg: theme.syntaxType },
    number: { fg: theme.syntaxNumber },
    boolean: { fg: theme.syntaxNumber },
    constant: { fg: theme.syntaxNumber },
    property: { fg: theme.syntaxNumber },
    operator: { fg: theme.syntaxOperator },
    punctuation: { fg: theme.syntaxPunctuation },
    variable: { fg: theme.syntaxVariable },
    parameter: { fg: theme.syntaxVariableBuiltin },
} as const;

export function MarkdownPart({
    text,
    streaming,
}: {
    text: string;
    streaming: boolean;
}) {
    const syntaxStyle = useMemo(() => SyntaxStyle.fromStyles(SYNTAX_STYLES), []);
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
