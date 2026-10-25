/** Display-column helpers. Terminals count CJK as two columns, so string
 *  length is not a usable width unit. Bun.stringWidth already implements the
 *  same wcwidth rules the renderer uses; there is no OpenTUI export for it. */
export function displayWidth(text: string): number {
    return Bun.stringWidth(text);
}

/** Truncate from the end, keeping *width* display columns including the ellipsis. */
export function truncateEnd(text: string, width: number): string {
    if (width <= 0) return "";
    if (displayWidth(text) <= width) return text;
    if (width === 1) return "…";
    let out = "";
    let used = 0;
    for (const char of text) {
        const charWidth = Bun.stringWidth(char);
        if (used + charWidth + 1 > width) break;
        out += char;
        used += charWidth;
    }
    return `${out}…`;
}

/** Truncate in the middle, keeping both ends of *text* within *width*. */
export function truncateMiddle(text: string, width: number): string {
    if (width <= 0) return "";
    if (displayWidth(text) <= width) return text;
    if (width === 1) return "…";

    const chars = Array.from(text);
    const budget = width - 1;
    const leftBudget = Math.ceil(budget / 2);
    const rightBudget = budget - leftBudget;

    let left = "";
    let leftWidth = 0;
    for (const char of chars) {
        const charWidth = Bun.stringWidth(char);
        if (leftWidth + charWidth > leftBudget) break;
        left += char;
        leftWidth += charWidth;
    }

    let right = "";
    let rightWidth = 0;
    for (let index = chars.length - 1; index >= 0; index--) {
        const char = chars[index]!;
        const charWidth = Bun.stringWidth(char);
        if (rightWidth + charWidth > rightBudget) break;
        right = char + right;
        rightWidth += charWidth;
    }

    return `${left}…${right}`;
}
