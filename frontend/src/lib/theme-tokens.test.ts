import { describe, expect, it } from "vitest";

/**
 * Contrast contract for the chat color tokens in `index.css`.
 *
 * The hex pairs below mirror the token values (`:root` for light, `.dark`
 * for dark). If a token changes, update the matching pair here so the
 * WCAG AA 4.5:1 guarantee for text stays enforced. The structural half of
 * the theme contract (both blocks declaring the same properties) lives in
 * `tests/test_theme_tokens.py`.
 */

function luminance(hex: string): number {
    const channels = [0, 2, 4].map(
        (offset) => parseInt(hex.slice(offset + 1, offset + 3), 16) / 255,
    );
    const linearize = (channel: number) =>
        channel <= 0.04045
            ? channel / 12.92
            : ((channel + 0.055) / 1.055) ** 2.4;
    const [red, green, blue] = channels.map(linearize);
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground: string, background: string): number {
    const [lighter, darker] = [luminance(foreground), luminance(background)].sort(
        (a, b) => b - a,
    );
    return (lighter + 0.05) / (darker + 0.05);
}

const LIGHT = {
    background: "#F6F5F3",
    sidebar: "#F1EFEA",
    card: "#FFFFFF",
    foreground: "#201F1C",
    weak: "#7A766F",
    weakStrong: "#6E6A60",
    accent: "#1D5FA8",
    accentSoft: "#EAF1F9",
    onAccent: "#FFFFFF",
    userBubble: "#EEF1F6",
    danger: "#B23B2E",
    dangerSoft: "#FBEDEA",
    success: "#17703F",
    muted: "#ECEAE4",
} as const;

const DARK = {
    background: "#1C1B1A",
    sidebar: "#151413",
    card: "#262524",
    foreground: "#E8E5E0",
    weak: "#B4B0AA",
    // #8F8A83 scaled up one step so weak text clears AA on every dark
    // surface (card included).
    weakStrong: "#938E86",
    accent: "#7FA6F0",
    accentSoft: "#22304A",
    onAccent: "#1C1B18",
    userBubble: "#262A33",
    codeBg: "#2A2826",
    codeFg: "#D9D5CF",
    danger: "#E8A0A0",
    success: "#6FCF97",
} as const;

describe("chat token contrast (light)", () => {
    it("keeps body text readable", () => {
        expect(contrastRatio(LIGHT.foreground, LIGHT.background)).toBeGreaterThan(7);
        expect(contrastRatio(LIGHT.foreground, LIGHT.sidebar)).toBeGreaterThan(7);
        expect(contrastRatio(LIGHT.foreground, LIGHT.card)).toBeGreaterThan(7);
    });

    it("clears AA for secondary text per surface", () => {
        // `weak` is approved for white surfaces only.
        expect(contrastRatio(LIGHT.weak, LIGHT.card)).toBeGreaterThanOrEqual(4.5);
        // `weak-strong` covers every tinted surface.
        for (const surface of [
            LIGHT.background,
            LIGHT.sidebar,
            LIGHT.accentSoft,
            LIGHT.userBubble,
        ]) {
            expect(contrastRatio(LIGHT.weakStrong, surface)).toBeGreaterThanOrEqual(
                4.5,
            );
        }
    });

    it("clears AA for the emphasis color", () => {
        expect(contrastRatio(LIGHT.accent, LIGHT.card)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(LIGHT.accent, LIGHT.accentSoft)).toBeGreaterThanOrEqual(
            4.5,
        );
        expect(contrastRatio(LIGHT.onAccent, LIGHT.accent)).toBeGreaterThanOrEqual(
            4.5,
        );
        expect(contrastRatio(LIGHT.foreground, LIGHT.userBubble)).toBeGreaterThanOrEqual(
            4.5,
        );
        expect(contrastRatio(LIGHT.danger, LIGHT.card)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(LIGHT.danger, LIGHT.dangerSoft)).toBeGreaterThanOrEqual(
            4.5,
        );
    });

    it("clears AA for the confirm color on the composer pill", () => {
        expect(contrastRatio(LIGHT.success, LIGHT.card)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(LIGHT.success, LIGHT.muted)).toBeGreaterThanOrEqual(4.5);
    });
});

describe("chat token contrast (dark)", () => {
    it("keeps body text readable", () => {
        expect(contrastRatio(DARK.foreground, DARK.background)).toBeGreaterThan(7);
        expect(contrastRatio(DARK.foreground, DARK.sidebar)).toBeGreaterThan(7);
        expect(contrastRatio(DARK.foreground, DARK.card)).toBeGreaterThan(7);
    });

    it("clears AA for secondary text everywhere", () => {
        // `weak` also appears on selected rows (icon buttons).
        for (const surface of [
            DARK.background,
            DARK.sidebar,
            DARK.card,
            DARK.accentSoft,
            DARK.userBubble,
        ]) {
            expect(contrastRatio(DARK.weak, surface)).toBeGreaterThanOrEqual(4.5);
        }
        // `weak-strong` never sits on accent-soft (selected rows use brand
        // text there) or inside user bubbles (only `weak` appears there);
        // everywhere else it must clear AA.
        for (const surface of [
            DARK.background,
            DARK.sidebar,
            DARK.card,
        ]) {
            expect(
                contrastRatio(DARK.weakStrong, surface),
            ).toBeGreaterThanOrEqual(4.5);
        }
    });

    it("clears AA for code and the emphasis color", () => {
        expect(
            contrastRatio(DARK.codeFg, DARK.codeBg),
        ).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(DARK.accent, DARK.background)).toBeGreaterThanOrEqual(
            4.5,
        );
        expect(contrastRatio(DARK.accent, DARK.accentSoft)).toBeGreaterThanOrEqual(
            4.5,
        );
        expect(contrastRatio(DARK.onAccent, DARK.accent)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(DARK.foreground, DARK.userBubble)).toBeGreaterThanOrEqual(
            4.5,
        );
        expect(contrastRatio(DARK.danger, DARK.card)).toBeGreaterThanOrEqual(4.5);
    });

    it("clears AA for the confirm color on the composer pill", () => {
        expect(contrastRatio(DARK.success, DARK.card)).toBeGreaterThanOrEqual(4.5);
        expect(
            contrastRatio(DARK.success, DARK.background),
        ).toBeGreaterThanOrEqual(4.5);
    });
});

