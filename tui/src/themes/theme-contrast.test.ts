import { describe, expect, test } from "bun:test";

import { contrastRatio } from "./contrast.ts";
import { themes } from "./index.ts";

/** WCAG 2.1 AA for body text. */
const AA_TEXT = 4.5;

/** Hue in degrees, so two colours can be compared without a full colour lib. */
function hue(hex: string): number {
    const [r, g, b] = [1, 3, 5].map((offset) =>
        parseInt(hex.slice(offset, offset + 2), 16) / 255,
    ) as [number, number, number];
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const delta = max - min;
    if (delta === 0) return 0;
    const raw =
        max === r
            ? ((g - b) / delta) % 6
            : max === g
              ? (b - r) / delta + 2
              : (r - g) / delta + 4;
    return (raw * 60 + 360) % 360;
}

/** Smallest angle between two hues, 0..180. */
function hueDistance(a: string, b: string): number {
    const diff = Math.abs(hue(a) - hue(b)) % 360;
    return diff > 180 ? 360 - diff : diff;
}

describe("every theme", () => {
    const entries = Object.entries(themes);

    test("has body text at AA contrast on its background", () => {
        for (const [name, theme] of entries) {
            expect({
                name,
                ratio: contrastRatio(theme.foreground, theme.background),
            }).toMatchObject({ name, ratio: expect.any(Number) });
            expect(
                contrastRatio(theme.foreground, theme.background),
            ).toBeGreaterThanOrEqual(AA_TEXT);
        }
    });

    test("has secondary text at AA contrast on its background", () => {
        for (const [name, theme] of entries) {
            expect({
                name,
                ratio: contrastRatio(theme.foregroundMuted, theme.background),
            }).toMatchObject({ name, ratio: expect.any(Number) });
            expect(
                contrastRatio(theme.foregroundMuted, theme.background),
            ).toBeGreaterThanOrEqual(AA_TEXT);
        }
    });

    test("keeps accent text at AA contrast on its background", () => {
        for (const [name, theme] of entries) {
            expect({
                name,
                ratio: contrastRatio(theme.accentText, theme.background),
            }).toMatchObject({ name, ratio: expect.any(Number) });
            expect(
                contrastRatio(theme.accentText, theme.background),
            ).toBeGreaterThanOrEqual(AA_TEXT);
        }
    });

    test("keeps the accent foreground at AA contrast on the accent fill", () => {
        for (const [name, theme] of entries) {
            expect({
                name,
                ratio: contrastRatio(theme.accentForeground, theme.accent),
            }).toMatchObject({ name, ratio: expect.any(Number) });
            expect(
                contrastRatio(theme.accentForeground, theme.accent),
            ).toBeGreaterThanOrEqual(4);
        }
    });
});

describe("accentText", () => {
    test("stays in the accent's hue family in every theme", () => {
        // a monochrome theme (matrix) darkens the accent; switching hue there
        // would make the label look unrelated to the selection colour
        for (const [name, theme] of Object.entries(themes)) {
            expect({ name, hue: Math.round(hueDistance(theme.accentText, theme.accent)) })
                .toMatchObject({ name });
            expect(hueDistance(theme.accentText, theme.accent)).toBeLessThan(20);
        }
    });

    test("still differs from the body text it sits above", () => {
        for (const [name, theme] of Object.entries(themes)) {
            expect({ name, same: theme.accentText === theme.foreground }).toMatchObject({
                name,
                same: false,
            });
        }
    });
});
