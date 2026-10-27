import { describe, expect, test } from "bun:test";

import { contrastRatio } from "./contrast.ts";
import { dimTheme } from "./dim.ts";
import { themes } from "./index.ts";

describe("dimTheme", () => {
    const theme = themes.dark!;

    test("leaves the canvas alone but dims raised surfaces", () => {
        const dim = dimTheme(theme);
        expect(dim.background.base).toBe(theme.background.base);
        expect(dim.background.raised).not.toBe(theme.background.raised);
    });

    test("pulls text towards the background", () => {
        const dim = dimTheme(theme, 0.55);
        expect(dim.text.base).not.toBe(theme.text.base);
        expect(dim.primary.muted).not.toBe(theme.primary.muted);
    });

    test("lowers contrast against the background", () => {
        const dim = dimTheme(theme, 0.55);
        expect(
            contrastRatio(dim.text.base, dim.background.base),
        ).toBeLessThan(
            contrastRatio(theme.text.base, theme.background.base),
        );
    });

    test("recurses into grouped tokens", () => {
        const dim = dimTheme(theme, 0.5);
        expect(dim.diff.addedBg).not.toBe(theme.diff.addedBg);
        expect(dim.syntax.keyword).not.toBe(theme.syntax.keyword);
    });

    test("keeps every theme's dimmed body text above the background", () => {
        for (const [name, palette] of Object.entries(themes)) {
            const dim = dimTheme(palette);
            expect({ name, fg: dim.text.base }).toMatchObject({ name });
            expect(dim.text.base).not.toBe(dim.background.base);
        }
    });
});
