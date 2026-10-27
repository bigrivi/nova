/** Launch-screen animation state, kept free of React so it is testable. */

/** Frame interval for the composer border pulse. */
export const TICK_MS = 150;

/** How long one placeholder hint stays on screen. */
export const HINT_MS = 4800;

/** Ticks for one full breathe in and out. */
const BREATH_TICKS = 24;

/** Placeholders cycled by the launch composer. */
export const HINTS = [
    "Ask anything, or type / for commands",
    "Describe what you want to change...",
    "Paste an error, I'll track it down...",
];

/** 0 at rest, 1 fully lit, triangle wave so the border eases both ways. */
export function breath(tick: number): number {
    const phase = (tick % BREATH_TICKS) / BREATH_TICKS;
    return 1 - Math.abs(phase * 2 - 1);
}

/** The hint shown on rotation *index*, wrapping around *options*. */
export function hintAt(index: number, options: readonly string[]): string {
    if (options.length === 0) return "";
    return options[index % options.length]!;
}
