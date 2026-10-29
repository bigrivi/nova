/** Which slice of a long suggestion list is on screen.
 *
 *  The popup used to render items 0..5 regardless of the cursor, so anything
 *  below the fold — every file in a directory with more than six entries — could
 *  be selected but never seen. This is the arithmetic that fixes that, kept pure
 *  so it can be asserted without a renderer.
 */
export type SuggestionWindow = {
    start: number;
    /** Rows hidden above the window. */
    hiddenAbove: number;
    /** Rows hidden below the window. */
    hiddenBelow: number;
};

export function windowAround(
    index: number,
    total: number,
    rows = 6,
): SuggestionWindow {
    if (total <= 0) {
        return { start: 0, hiddenAbove: 0, hiddenBelow: 0 };
    }
    const size = Math.min(rows, total);
    // Two rows of context above the cursor, but never past the end of the list.
    const start = Math.max(0, Math.min(index - 2, total - size));
    return {
        start,
        hiddenAbove: start,
        hiddenBelow: Math.max(0, total - start - size),
    };
}
