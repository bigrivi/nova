/** Colour maths shared by the theme layer and the launch animations. */

/** Split `#rrggbb` into 0..255 channels. */
export function channels(hex: string): [number, number, number] {
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
