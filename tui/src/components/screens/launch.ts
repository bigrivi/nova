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

/** 0 at rest, 1 fully lit, cosine wave so the border eases at both ends. */
export function breath(tick: number): number {
    return (1 - Math.cos((2 * Math.PI * (tick % BREATH_TICKS)) / BREATH_TICKS)) / 2;
}

/** The hint shown on rotation *index*, wrapping around *options*. */
export function hintAt(index: number, options: readonly string[]): string {
    if (options.length === 0) return "";
    return options[index % options.length]!;
}

/** Whether the pulse and the hint rotation should run.
 *
 *  `NO_COLOR` (no-colour terminals) and `NOVA_MOTION=0` both mean "hold still":
 *  screen recordings and reduced-motion users get a static card.
 */
export function motionEnabled(env: Record<string, string | undefined>): boolean {
    return env.NOVA_MOTION !== "0" && env.NO_COLOR === undefined;
}

/** Hints for a composer, leading with the saved sessions when there are any. */
export function buildHints(savedSessions: number): string[] {
    if (savedSessions <= 0) return [...HINTS];
    const label = savedSessions === 1 ? "1 saved session" : `${savedSessions} saved sessions`;
    return [`${label} · /sessions to resume`, ...HINTS];
}
