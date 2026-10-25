import { describe, expect, test } from "bun:test";
import { displayWidth } from "./display-width.ts";
import {
    SHORTCUTS_COMPACT,
    contextTier,
    SHORTCUTS_FULL,
    formatTokens,
    renderBar,
    shortenPath,
    shortcutText,
    statusDensity,
} from "./status-format.ts";

describe("formatTokens", () => {
    test("keeps small numbers", () => {
        expect(formatTokens(999)).toBe("999");
    });

    test("uses k above one thousand", () => {
        expect(formatTokens(1000)).toBe("1k");
        expect(formatTokens(62_800)).toBe("62.8k");
    });

    test("uses M above one million", () => {
        expect(formatTokens(1_000_000)).toBe("1M");
        expect(formatTokens(1_500_000)).toBe("1.5M");
    });
});

describe("contextTier", () => {
    test("stays normal below 60", () => {
        expect(contextTier(59)).toBe("normal");
    });

    test("warns from 60 to 84", () => {
        expect(contextTier(60)).toBe("warning");
        expect(contextTier(84)).toBe("warning");
    });

    test("is critical at 85 and above", () => {
        expect(contextTier(85)).toBe("danger");
        expect(contextTier(100)).toBe("danger");
    });
});

describe("renderBar", () => {
    test("is empty at zero", () => {
        expect(renderBar(0)).toBe("▱".repeat(10));
    });

    test("lights one cell for a tiny non-zero value", () => {
        expect(renderBar(1)).toBe("▰" + "▱".repeat(9));
    });

    test("rounds to the nearest cell", () => {
        expect(renderBar(50)).toBe("▰".repeat(5) + "▱".repeat(5));
        expect(renderBar(100)).toBe("▰".repeat(10));
    });
});

describe("statusDensity", () => {
    test("keeps everything at 120 and 80 columns", () => {
        expect(statusDensity(120).compactHints).toBe(false);
        expect(statusDensity(80).compactHints).toBe(false);
        expect(statusDensity(80).hideBar).toBe(false);
    });

    test("drops hints before the bar", () => {
        expect(statusDensity(79).compactHints).toBe(true);
        expect(statusDensity(79).hideBar).toBe(false);
    });

    test("drops the bar before the numbers", () => {
        expect(statusDensity(60).hideBar).toBe(true);
        expect(statusDensity(60).hideNumbers).toBe(false);
    });

    test("drops the numbers before the provider", () => {
        expect(statusDensity(50).hideNumbers).toBe(true);
        expect(statusDensity(50).hideProvider).toBe(false);
    });

    test("drops the provider on very narrow terminals", () => {
        expect(statusDensity(40).hideProvider).toBe(true);
    });
});

describe("shortcutText", () => {
    test("measures the full and compact rows", () => {
        expect(shortcutText(SHORTCUTS_FULL)).toBe(
            "⏎ send  ⇧⏎ newline  ^C exit  / cmds",
        );
        expect(shortcutText(SHORTCUTS_COMPACT)).toBe("^C exit  / cmds");
    });
});

describe("shortenPath", () => {
    const home = "/Users/andy";

    test("replaces the home prefix", () => {
        expect(
            shortenPath(`${home}/Workspace/projects/winking/wkccd`, home, 100),
        ).toBe("~/Workspace/projects/winking/wkccd");
    });

    test("keeps the last two segments when narrow", () => {
        expect(
            shortenPath(`${home}/Workspace/projects/winking/wkccd`, home, 20),
        ).toBe("~/…/winking/wkccd");
    });

    test("falls back to one segment", () => {
        expect(
            shortenPath(`${home}/Workspace/projects/winking/wkccd`, home, 12),
        ).toBe("~/…/wkccd");
    });

    test("middle-truncates when even one segment is too wide", () => {
        const result = shortenPath(
            `${home}/Workspace/projects/winking/wkccd`,
            home,
            6,
        );
        expect(displayWidth(result)).toBeLessThanOrEqual(6);
        expect(result).toContain("…");
    });

    test("handles CJK path segments by display width", () => {
        const result = shortenPath(`${home}/项目/wkccd`, home, 10);
        expect(result).toBe("~/…/wkccd");
        expect(displayWidth(result)).toBeLessThanOrEqual(10);
    });
});
