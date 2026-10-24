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

export function stripAnsi(text: string): string {
    return text.replace(/\x1b\[[0-9;]*m/g, "");
}

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
    const trimmed = text.replace(/\r/g, "").replace(/\n+$/, "");
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
    const lines = text.replace(/\r/g, "\n").split("\n");
    while (lines.length > 0 && lines[0]!.trim() === "") {
        lines.shift();
    }
    while (lines.length > 0 && lines[lines.length - 1]!.trim() === "") {
        lines.pop();
    }
    return lines.map((line) => line.trimEnd());
}

export function stripProgress(text: string): string {
    return text
        .split("\n")
        .map((line) => line.split("\r").pop() ?? "")
        .join("\n");
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
