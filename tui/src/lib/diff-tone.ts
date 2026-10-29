/** Colour for one line of a unified diff. */
import type { Theme } from "../themes/types.ts";

export function diffLineTone(line: string, theme: Theme): string {
    if (line.startsWith("+++") || line.startsWith("---")) return theme.text.muted;
    if (line.startsWith("@@")) return theme.primary.muted;
    if (line.startsWith("+")) return theme.diff.addedSign;
    if (line.startsWith("-")) return theme.diff.removedSign;
    return theme.text.base;
}
