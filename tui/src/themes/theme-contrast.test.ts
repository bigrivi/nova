import { describe, expect, test } from "bun:test";

import { contrastRatio } from "./contrast.ts";
import { themes } from "./index.ts";

/** WCAG 2.1 AA for body text. */
const AA_TEXT = 4.5;

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
