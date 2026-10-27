/** Contrast helpers for picking a foreground that survives a coloured fill. */

/** sRGB channel (0..255) to linear light, per WCAG 2.1. */
function linear(channel: number): number {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance of a `#rrggbb` colour, 0 (black) .. 1 (white). */
export function luminance(hex: string): number {
    const [r, g, b] = [1, 3, 5].map((offset) =>
        linear(parseInt(hex.slice(offset, offset + 2), 16)),
    ) as [number, number, number];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two `#rrggbb` colours, 1 .. 21. */
export function contrastRatio(a: string, b: string): number {
    const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [
        number,
        number,
    ];
    return (light + 0.05) / (dark + 0.05);
}
