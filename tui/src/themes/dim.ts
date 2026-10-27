/** Dimming for the quiet layer behind a modal.
 *
 *  A translucent full-screen fill cannot be used for this: compositing it per
 *  cell drops double-width glyphs (CJK), so the transcript would lose words.
 *  Recolouring the palette instead keeps every glyph intact.
 */
import { mixColor } from "./color.ts";
import type { Theme } from "./types.ts";

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
            return mixColor(value, theme.background.base, amount);
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
