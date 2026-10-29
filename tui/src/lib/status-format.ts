/** Pure formatting and layout rules for the bottom status bar. */
import { displayWidth, truncateMiddle } from "./display-width.ts";

/** `62.8k`, `1M`, `999` — one decimal, trailing `.0` dropped. */
export function formatTokens(value: number): string {
    if (!Number.isFinite(value) || value <= 0) return "0";
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
    }
    if (value >= 1000) {
        return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
    }
    return String(Math.round(value));
}

/** Ten-cell meter; any non-zero usage lights at least one cell. */
export function renderBar(percent: number, cells = 10): string {
    const clamped = Math.max(0, Math.min(100, percent));
    if (cells <= 0) return "";
    let filled = Math.round((clamped / 100) * cells);
    if (clamped > 0 && filled === 0) filled = 1;
    filled = Math.min(cells, filled);
    return "▰".repeat(filled) + "▱".repeat(cells - filled);
}

export type ContextTier = "normal" | "warning" | "danger";

/** Colour tier for context usage: 60% warns, 85% is critical. */
export function contextTier(percent: number): ContextTier {
    if (percent >= 85) return "danger";
    if (percent >= 60) return "warning";
    return "normal";
}

export type StatusDensity = {
    /** Hide the secondary shortcuts, keeping `^C exit` and `/ cmds`. */
    compactHints: boolean;
    /** Hide the context meter bar. */
    hideBar: boolean;
    /** Hide the `used/limit` numbers. */
    hideNumbers: boolean;
    /** Drop the provider name, keeping the status dot and model name. */
    hideProvider: boolean;
    /** Drop the permission-mode chip. */
    hideMode: boolean;
    /** Drop the git branch from the environment line. */
    hideBranch: boolean;
};

/**
 * Decide which optional pieces to drop for *width* columns.
 *
 * Order matters: hints, then bar, then numbers, then provider/branch. The
 * status dot and model name are never dropped.
 */
export function statusDensity(width: number): StatusDensity {
    return {
        compactHints: width < 80,
        hideBar: width < 68,
        hideNumbers: width < 54,
        hideProvider: width < 48,
        hideMode: width < 58,
        hideBranch: width < 64,
    };
}

export type Shortcut = {
    key: string;
    label: string;
};

export const SHORTCUTS_FULL: readonly Shortcut[] = [
    { key: "⏎", label: "send" },
    { key: "⇧⏎", label: "newline" },
    { key: "^C", label: "exit" },
    { key: "/", label: "cmds" },
];

export const SHORTCUTS_COMPACT: readonly Shortcut[] = [
    { key: "^C", label: "exit" },
    { key: "/", label: "cmds" },
];

/** The plain text used to measure a shortcut row. */
export function shortcutText(shortcuts: readonly Shortcut[]): string {
    return shortcuts.map((item) => `${item.key} ${item.label}`).join("  ");
}

/**
 * Shorten an absolute path for the environment line.
 *
 * Replaces the home directory with `~`, then keeps the last two segments
 * (`~/…/winking/wkccd`). Falls back to one segment and finally to a middle
 * ellipsis when the width is still too small.
 */
export function shortenPath(path: string, home: string, width: number): string {
    if (width <= 0) return "";
    const normalizedHome = home.replace(/\/+$/, "");
    let compact = path;
    if (
        normalizedHome &&
        (path === normalizedHome || path.startsWith(`${normalizedHome}/`))
    ) {
        compact = `~${path.slice(normalizedHome.length)}` || "~";
    }
    if (displayWidth(compact) <= width) return compact;

    const segments = compact.split("/").filter((segment) => segment.length > 0);
    const leaf = segments.at(-1) ?? compact;
    const parent = segments.at(-2);
    const prefix = compact.startsWith("~") ? "~/" : "";
    const twoLevel = parent
        ? `${prefix}…/${parent}/${leaf}`
        : `${prefix}…/${leaf}`;
    if (displayWidth(twoLevel) <= width) return twoLevel;

    const oneLevel = `${prefix}…/${leaf}`;
    if (displayWidth(oneLevel) <= width) return oneLevel;

    return truncateMiddle(compact, width);
}
