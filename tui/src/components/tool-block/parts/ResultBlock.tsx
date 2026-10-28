import { useTheme } from "../../../context/theme.tsx";
import { plural, RESULT_LIMITS } from "../format/text.ts";
import type { ResultView } from "../types.ts";
import { DiffView } from "./DiffView.tsx";

/** How many rows are shown, and how the hint reads, for one view. */
function fold(lines: string[], expanded: boolean, limit: number) {
    const maxVisible = expanded ? RESULT_LIMITS.expandedMax : limit;
    const hidden = Math.max(0, lines.length - maxVisible);
    return {
        hidden,
        hint:
            hidden > 0
                ? `… +${hidden} ${plural(hidden, "line")}`
                : null,
    };
}

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
        return (
            <DiffView
                diff={view.diff}
                synthesized={view.synthesized}
                truncated={view.truncated}
                hiddenLines={view.hiddenLines}
            />
        );
    }

    // Blank output lines would otherwise render as a lone gutter glyph.
    const lines = view.lines.filter((line) => line.trim().length > 0);
    const limit = view.limit ?? RESULT_LIMITS.generic;
    const { hidden, hint } = fold(lines, expanded, limit);
    const visible =
        view.hiddenAt === "top" ? lines.slice(hidden) : lines.slice(0, lines.length - hidden);
    // Expanded output is capped too; collapsing would not reveal more, so the
    // hint stops advertising a key that cannot help.
    const suffix = expanded ? "" : " (ctrl+o to expand)";

    return (
        <box flexDirection="column">
            {view.hiddenAt === "top" && hint ? (
                <text fg={theme.text.muted} content={`  ${hint}${suffix}`} />
            ) : null}
            {visible.map((line, index) => (
                <text
                    key={index}
                    fg={theme.text.muted}
                    content={`${index === 0 ? "  └ " : "    "}${line}`}
                />
            ))}
            {view.hiddenAt === "bottom" && hint ? (
                <text fg={theme.text.muted} content={`  ${hint}${suffix}`} />
            ) : null}
        </box>
    );
}
