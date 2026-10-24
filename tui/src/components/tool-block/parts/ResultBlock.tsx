import { useTheme } from "../../../context/theme.tsx";
import { RESULT_LIMITS } from "../format/text.ts";
import type { ResultView } from "../types.ts";
import { DiffView } from "./DiffView.tsx";

export function ResultBlock({
    view,
    expanded,
}: {
    view: ResultView;
    expanded: boolean;
}) {
    const theme = useTheme();
    if (view.kind === "none") return null;
    if (view.kind === "diff") {
        return <DiffView diff={view.diff} synthesized={view.synthesized} />;
    }

    // Blank output lines would otherwise render as a lone gutter glyph.
    const lines = view.lines.filter((line) => line.trim().length > 0);
    const limit = view.limit ?? RESULT_LIMITS.generic;
    const maxVisible = expanded ? RESULT_LIMITS.expandedMax : limit;
    const hiddenCount = Math.max(0, lines.length - maxVisible);
    const visible =
        view.hiddenAt === "top" ? lines.slice(hiddenCount) : lines.slice(0, maxVisible);

    const foldedText =
        hiddenCount > 0
            ? view.hiddenAt === "top"
                ? `  … +${hiddenCount} lines${expanded ? " more" : " (ctrl+o to expand)"}`
                : `  … +${hiddenCount} lines${expanded ? " more" : " (ctrl+o to expand)"}`
            : null;

    return (
        <box flexDirection="column">
            {view.hiddenAt === "top" && foldedText ? (
                <text fg={theme.muted} content={foldedText} />
            ) : null}
            {visible.map((line, index) => (
                <text
                    key={index}
                    fg={theme.muted}
                    content={`${index === 0 ? "  └ " : "    "}${line}`}
                />
            ))}
            {view.hiddenAt === "bottom" && foldedText ? (
                <text fg={theme.muted} content={foldedText} />
            ) : null}
        </box>
    );
}
