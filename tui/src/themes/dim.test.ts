import { describe, expect, test } from "bun:test";

import { contrastRatio } from "./contrast.ts";
import { dimTheme } from "./dim.ts";
import { themes } from "./index.ts";

describe("dimTheme", () => {
    const theme = themes.dark!;

    test("leaves the background alone", () => {
        expect(dimTheme(theme).background).toBe(theme.background);
    });

    test("pulls text towards the background", () => {
        const dim = dimTheme(theme, 0.55);
        expect(dim.foreground).not.toBe(theme.foreground);
        expect(dim.accentText).not.toBe(theme.accentText);
    });

    test("lowers contrast against the background", () => {
        const dim = dimTheme(theme, 0.55);
        expect(contrastRatio(dim.foreground, dim.background)).toBeLessThan(
            contrastRatio(theme.foreground, theme.background),
        );
    });

    test("recurses into grouped tokens", () => {
        const dim = dimTheme(theme, 0.5);
        expect(dim.diff.addedBg).not.toBe(theme.diff.addedBg);
    });

    test("keeps every theme's dimmed body text above the background", () => {
        for (const [name, palette] of Object.entries(themes)) {
            const dim = dimTheme(palette);
            expect({ name, fg: dim.foreground }).toMatchObject({ name });
            expect(dim.foreground).not.toBe(dim.background);
        }
    });
});
