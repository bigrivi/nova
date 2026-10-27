/** Dimming for the quiet layer behind a modal.
 *
 *  A translucent full-screen fill cannot be used for this: compositing it per
 *  cell drops double-width glyphs (CJK), so the transcript would lose words.
 *  Recolouring the palette instead keeps every glyph intact.
 */
import type { Theme } from "./types.ts";

function channels(hex: string): [number, number, number] {
    return [1, 3, 5].map((offset) =>
        parseInt(hex.slice(offset, offset + 2), 16),
    ) as [number, number, number];
}

/** Linear mix of two `#rrggbb` colours; `amount` 0 keeps *from*, 1 returns *to*. */
export function mixColor(from: string, to: string, amount: number): string {
    const [r1, g1, b1] = channels(from);
    const [r2, g2, b2] = channels(to);
    const mix = (a: number, b: number) => Math.round(a + (b - a) * amount);
    return `#${[mix(r1, r2), mix(g1, g2), mix(b1, b2)]
        .map((value) => value.toString(16).padStart(2, "0"))
        .join("")}`;
}

/**
 * The same theme with every colour pulled towards its background.
 *
 * Args:
 *   theme: Palette to dim.
 *   amount: 0 keeps the palette, 1 leaves every colour at the background.
 *
 * Returns:
 *   A theme whose background is unchanged, because a colour blended towards
 *   itself is itself.
 */
export function dimTheme(theme: Theme, amount = 0.55): Theme {
    const map = (value: unknown): unknown => {
        if (typeof value === "string") {
            return mixColor(value, theme.background, amount);
        }
        if (value !== null && typeof value === "object") {
            return Object.fromEntries(
                Object.entries(value).map(([key, inner]) => [key, map(inner)]),
            );
        }
        return value;
    };
    return map(theme) as Theme;
}
