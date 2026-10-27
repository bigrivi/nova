/** Launch-screen animation state, kept free of React so it is testable. */

/** Frame interval for the border pulse and the placeholder cycle. */
export const TICK_MS = 150;

/** Ticks for one full breathe in and out. */
const BREATH_TICKS = 24;

/** Ticks a placeholder stays on screen before the next one. */
const PLACEHOLDER_TICKS = 32;

/** 0 at rest, 1 fully lit, triangle wave so the border eases both ways. */
export function breath(tick: number): number {
    const phase = (tick % BREATH_TICKS) / BREATH_TICKS;
    return 1 - Math.abs(phase * 2 - 1);
}

/** The placeholder shown at *tick*, cycling through *options*. */
export function placeholderAt(tick: number, options: readonly string[]): string {
    if (options.length === 0) return "";
    const index = Math.floor(tick / PLACEHOLDER_TICKS) % options.length;
    return options[index]!;
}
