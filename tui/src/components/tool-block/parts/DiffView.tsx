import { SyntaxStyle, getTreeSitterClient } from "@opentui/core";
import { useTerminalDimensions } from "@opentui/react";
import { useMemo } from "react";
import { useTheme } from "../../../context/theme.tsx";
import { buildSyntaxStyles } from "../../parts/MarkdownPart.tsx";

/** Terminal columns required before a diff switches from unified to split. */
const SPLIT_VIEW_MIN_COLS = 124;

export function DiffView({ diff, synthesized }: { diff: string; synthesized: boolean }) {
    const theme = useTheme();
    const dims = useTerminalDimensions();
    const syntaxStyle = useMemo(() => SyntaxStyle.fromStyles(buildSyntaxStyles(theme)), [theme]);
    const treeSitterClient = useMemo(() => getTreeSitterClient(), []);
    const view = dims.width > SPLIT_VIEW_MIN_COLS ? "split" : "unified";

    return (
        <box backgroundColor={theme.diff.contextBg} paddingLeft={4} paddingBottom={1} paddingTop={1}>
            <diff
                width="100%"
                diff={diff}
                view={view}
                showLineNumbers={!synthesized}
                fg={theme.text.base}
                addedBg={theme.diff.addedBg}
                removedBg={theme.diff.removedBg}
                addedSignColor={theme.diff.addedSign}
                removedSignColor={theme.diff.removedSign}
                lineNumberFg={theme.diff.lineNumber}
                addedLineNumberBg={theme.diff.addedLineNumberBg}
                removedLineNumberBg={theme.diff.removedLineNumberBg}
                syntaxStyle={syntaxStyle}
                treeSitterClient={treeSitterClient}
                wrapMode="word"
            />
        </box>
    );
}
