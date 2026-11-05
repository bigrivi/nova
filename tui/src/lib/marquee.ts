/** Hover marquee for session-tab titles.
 *
 *  Ported from opencode's marquee: wait, then scroll exactly one full cycle and
 *  rest back at the start. Slicing is by display columns, so CJK titles keep
 *  their cell alignment.
 */
import { displayWidth } from "./display-width.ts";

export const MARQUEE_DELAY_MS = 600;
export const MARQUEE_TICK_MS = 80;
export const MARQUEE_GAP = " · ";

const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });

function graphemes(text: string): string[] {
    return Array.from(segmenter.segment(text), (part) => part.segment);
}

/** Keep at most *width* display columns from the start of *text*. */
export function takeWidth(text: string, width: number): string {
    if (width <= 0) return "";
    let out = "";
    let used = 0;
    for (const grapheme of graphemes(text)) {
        const cell = displayWidth(grapheme);
        if (used + cell > width) break;
        out += grapheme;
        used += cell;
    }
    return out;
}

/** Take *width* columns starting *offset* columns into *text*. */
export function sliceByWidth(
    text: string,
    width: number,
    offset: number,
): string {
    if (width <= 0) return "";
    if (offset <= 0) return takeWidth(text, width);

    let skipped = 0;
    let used = 0;
    let out = "";
    for (const grapheme of graphemes(text)) {
        const cell = displayWidth(grapheme);
        if (skipped + cell <= offset) {
            skipped += cell;
            continue;
        }
        if (skipped < offset) {
            // A double-width glyph straddles the start; skip it whole rather
            // than drawing half a character.
            skipped += cell;
            continue;
        }
        if (used + cell > width) break;
        out += grapheme;
        used += cell;
    }
    return out;
}

export function marqueeCycleWidth(title: string): number {
    return displayWidth(title + MARQUEE_GAP);
}

export function marqueeOverflows(title: string, width: number): boolean {
    return displayWidth(title) > width;
}

/** The visible frame for *offset* columns into one looping title. */
export function marqueeFrame(
    title: string,
    width: number,
    offset: number,
): string {
    if (width <= 0 || title.length === 0) return "";
    if (marqueeOverflows(title, width) === false || offset <= 0) {
        return takeWidth(title, width);
    }
    const cycle = marqueeCycleWidth(title);
    if (cycle <= 0) return "";
    const loop = title + MARQUEE_GAP + title + MARQUEE_GAP;
    return sliceByWidth(loop, width, offset % cycle);
}
