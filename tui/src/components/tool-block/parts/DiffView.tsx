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
        <box paddingLeft={2} marginTop={1}>
            <diff
                diff={diff}
                view={view}
                showLineNumbers={!synthesized}
                fg={theme.foreground}
                addedBg={theme.diff.addedBg}
                removedBg={theme.diff.removedBg}
                contextBg={theme.diff.contextBg}
                addedSignColor={theme.diff.addedSign}
                removedSignColor={theme.diff.removedSign}
                lineNumberFg={theme.diff.lineNumber}
                lineNumberBg={theme.diff.lineNumberBg}
                addedLineNumberBg={theme.diff.addedLineNumberBg}
                removedLineNumberBg={theme.diff.removedLineNumberBg}
                syntaxStyle={syntaxStyle}
                treeSitterClient={treeSitterClient}
                wrapMode="word"
            />
        </box>
    );
}
