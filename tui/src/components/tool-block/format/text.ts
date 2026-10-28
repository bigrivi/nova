/** Shared text helpers for tool renderers. */
import type { RenderCtx, ResultView } from "../types.ts";

export const RESULT_LIMITS = {
    shellOk: 3,
    shellErr: 8,
    list: 5,
    diff: 20,
    generic: 3,
    todos: 8,
    expandedMax: 200,
} as const;

/** Bytes of the tail kept when sanitising streaming output. */
const TAIL_BYTES = 64 * 1024;
/** Columns a tab expands to. */
const TAB_WIDTH = 4;

// OSC (BEL or ST terminated, includes OSC 52 clipboard writes), then the other
// control strings (DCS/APC/PM/SOS), then CSI (cursor, clear, private modes),
// then two-character escapes. Order matters: ESC itself is a C0 control, so the
// sequences have to go before the catch-all below.
const OSC = /\x1b\][\s\S]*?(?:\x07|\x1b\\)/g;
const CONTROL_STRING = /\x1b[P^_X][\s\S]*?(?:\x1b\\|\x07)/g;
const CSI = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const ESCAPE = /\x1b[@-Z\\-_]/g;
const C0_C1 = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g;

/**
 * Normalise tool output for display.
 *
 * Keeps visible text only: CRLF collapses to one newline, a carriage return
 * keeps the last frame of a progress line, every ANSI/terminal control sequence
 * is dropped, remaining control characters are removed and tabs expand.
 *
 * Args:
 *   text: Raw output, possibly containing escape sequences and carriage returns.
 *
 * Returns:
 *   The same text with control sequences removed; Unicode is untouched.
 */
export function sanitizeOutput(text: string): string {
    const lines = text
        .replace(/\r\n/g, "\n")
        .split("\n")
        .map((line) => {
            const last = line.lastIndexOf("\r");
            return last >= 0 ? line.slice(last + 1) : line;
        });
    return lines
        .join("\n")
        .replace(OSC, "")
        .replace(CONTROL_STRING, "")
        .replace(CSI, "")
        .replace(ESCAPE, "")
        .replace(C0_C1, "")
        .replace(/\t/g, " ".repeat(TAB_WIDTH));
}

/**
 * Sanitise a single-line value such as a command or a page title.
 *
 * Args:
 *   text: Untrusted short text.
 *
 * Returns:
 *   Control sequences removed, newlines collapsed to single spaces, trimmed.
 */
export function sanitizeInline(text: string): string {
    return sanitizeOutput(text).replace(/\s+/g, " ").trim();
}

export { truncateMiddle } from "../../../lib/display-width.ts";

export function displayWidth(text: string): number {
    return Bun.stringWidth(text);
}

export function truncateToWidth(text: string, cols: number): string {
    if (cols <= 0) return "";
    let width = 0;
    let out = "";
    for (const char of text) {
        const charWidth = Bun.stringWidth(char);
        if (width + charWidth + 1 > cols) {
            return out + "…";
        }
        width += charWidth;
        out += char;
    }
    return out;
}

export function truncate(text: string, max = 60): string {
    const single = text.replace(/\s+/g, " ").trim();
    if (displayWidth(single) <= max) return single;
    return truncateToWidth(single, max);
}

export function backtick(value: string): string {
    return `\`${value}\``;
}

export function plural(n: number, singular: string, pluralForm?: string): string {
    if (n === 1) return singular;
    return pluralForm ?? `${singular}s`;
}

export function tailLines(text: string, n: number): string[] {
    if (n <= 0 || !text) return [];
    // Streaming output can be megabytes; sanitising the whole buffer on every
    // chunk is wasted work when only the tail is shown.
    const tail = text.length > TAIL_BYTES ? text.slice(-TAIL_BYTES) : text;
    const trimmed = sanitizeOutput(tail).replace(/\n+$/, "");
    const lines: string[] = [];
    let end = trimmed.length;
    while (end > 0 && lines.length < n) {
        const start = trimmed.lastIndexOf("\n", end - 1);
        lines.unshift(trimmed.slice(start + 1, end));
        end = start;
    }
    return lines;
}

export function cleanLines(text: string): string[] {
    const lines = sanitizeOutput(text).split("\n");
    while (lines.length > 0 && lines[0]!.trim() === "") {
        lines.shift();
    }
    while (lines.length > 0 && lines[lines.length - 1]!.trim() === "") {
        lines.pop();
    }
    return lines.map((line) => line.trimEnd());
}

export function errorResult<A>(ctx: RenderCtx<A>): ResultView {
    const lines = tailLines(ctx.outputText, RESULT_LIMITS.shellErr);
    if (lines.length > 0) {
        return {
            kind: "lines",
            lines,
            hidden: 0,
            hiddenAt: "bottom",
            limit: RESULT_LIMITS.shellErr,
        };
    }
    if (ctx.error) {
        return {
            kind: "lines",
            lines: [ctx.error],
            hidden: 0,
            hiddenAt: "bottom",
            limit: RESULT_LIMITS.shellErr,
        };
    }
    return { kind: "none" };
}
