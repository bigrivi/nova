/** Diff helpers for tool renderers. */
export function looksLikeDiff(text: string): boolean {
    const lines = text.split("\n");
    for (let i = 0; i < lines.length; i++) {
        if (/^@@ -\d+(,\d+)? \+\d+(,\d+)? @@/.test(lines[i]!)) {
            return true;
        }
        if (/^--- .+/.test(lines[i]!) && /^\+\+\+ .+/.test(lines[i + 1] ?? "")) {
            return true;
        }
    }
    return false;
}

const HUNK_HEADER = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/;
const TRUNCATION_MARKER = /^\[\.\.\. (\d+) more lines \.\.\.\]$/m;

/** Whether the hunk at *headerIndex* has exactly the lines its header promises. */
function isHunkComplete(lines: string[], headerIndex: number): boolean {
    const match = HUNK_HEADER.exec(lines[headerIndex] ?? "");
    if (!match) return false;
    const oldCount = Number(match[2] ?? 1);
    const newCount = Number(match[4] ?? 1);
    let oldSeen = 0;
    let newSeen = 0;
    for (let index = headerIndex + 1; index < lines.length; index++) {
        const line = lines[index] ?? "";
        if (HUNK_HEADER.test(line) || line.startsWith("--- ") || line.startsWith("+++ ")) {
            break;
        }
        const prefix = line[0];
        if (prefix === "+") newSeen += 1;
        else if (prefix === "-") oldSeen += 1;
        else if (prefix === " " || line === "") {
            oldSeen += 1;
            newSeen += 1;
        } else if (prefix !== "\\") {
            return false;
        }
    }
    return oldSeen === oldCount && newSeen === newCount;
}

/**
 * Extract a valid unified diff from a tool output that prefixes it with prose.
 *
 * Three things would otherwise make the result unparsable:
 * - a prose preamble (sliced off),
 * - a trailing blank context line (`" "`), which `trim()` deletes,
 * - a server-side `[... N more lines ...]` marker, which can sit inside a hunk
 *   whose body was cut. The marker is dropped and the incomplete trailing hunk
 *   is removed, so every shown header stays honest.
 */
export type ParsedToolDiff = {
    /** The diff that can be rendered; empty when the output carries none. */
    diff: string;
    /** The server cut the tail: the last hunk was dropped. */
    truncated: boolean;
    /** Lines the server said it omitted, when it said. */
    hiddenLines?: number;
};

/**
 * Extract a unified diff and report whether the server cut it short.
 *
 * Args:
 *   text: Tool output, possibly prefixed with prose and possibly truncated.
 *
 * Returns:
 *   The renderable diff, plus `truncated`/`hiddenLines` so the view can say so
 *   instead of quietly showing a shorter patch.
 */
export function parseToolDiff(text: string): ParsedToolDiff {
    const marker = TRUNCATION_MARKER.exec(text);
    const hiddenLines = marker ? Number(marker[1]) : undefined;
    const truncated = marker !== null;
    return {
        diff: extractDiff(text),
        truncated,
        ...(hiddenLines === undefined ? {} : { hiddenLines }),
    };
}

/** The diff alone, for callers that do not render truncation. */
export function extractDiff(text: string): string {
    // Anchor on a file header pair: prose can contain "--- " anywhere, and
    // starting there used to swallow the rest of the tool output.
    const all = text.split("\n");
    let start = -1;
    for (let index = 0; index < all.length - 1; index++) {
        if (/^--- .+/.test(all[index]!) && /^\+\+\+ .+/.test(all[index + 1]!)) {
            start = index;
            break;
        }
    }
    if (start < 0) return "";

    const lines = all
        .slice(start)
        .filter((line) => !TRUNCATION_MARKER.test(line));
    while (lines.length > 0 && lines[lines.length - 1] === "") {
        lines.pop();
    }

    const headers: number[] = [];
    lines.forEach((line, position) => {
        if (HUNK_HEADER.test(line)) headers.push(position);
    });
    // File headers with no hunk are not a diff: render nothing rather than an
    // empty diff box.
    if (headers.length === 0) return "";

    for (let position = headers.length - 1; position >= 0; position--) {
        const header = headers[position]!;
        if (isHunkComplete(lines, header)) {
            const next = headers[position + 1];
            return lines.slice(0, next ?? lines.length).join("\n");
        }
    }
    // Every hunk was cut short: a header-only patch would render as an empty
    // box, so report no diff at all.
    return "";
}

function splitFragment(value: string): string[] {
    if (value === "") return [];
    const lines = value.split("\n");
    if (lines.length > 0 && lines[lines.length - 1] === "") {
        lines.pop();
    }
    return lines;
}

export function buildEditDiff(fileName: string, oldStr: string, newStr: string): string {
    if (oldStr === "" && newStr === "") return "";

    const path = fileName.replace(/^\/+/, "");
    const a = splitFragment(oldStr);
    const b = splitFragment(newStr);

    let prefix = 0;
    while (prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) {
        prefix++;
    }
    let suffix = 0;
    while (
        suffix < a.length - prefix &&
        suffix < b.length - prefix &&
        a[a.length - 1 - suffix] === b[b.length - 1 - suffix]
    ) {
        suffix++;
    }

    const context = 3;
    const contextBefore = Math.min(context, prefix);
    const contextAfter = Math.min(context, suffix);
    const removed = a.slice(prefix, a.length - suffix);
    const added = b.slice(prefix, b.length - suffix);

    const oldStart = Math.max(0, prefix - contextBefore) + 1;
    const newStart = Math.max(0, prefix - contextBefore) + 1;
    const oldCount = contextBefore + removed.length + contextAfter;
    const newCount = contextBefore + added.length + contextAfter;

    const lines = [
        `--- a/${path}`,
        `+++ b/${path}`,
        `@@ -${oldStart},${oldCount} +${newStart},${newCount} @@`,
    ];

    for (let i = prefix - contextBefore; i < prefix; i++) {
        lines.push(` ${a[i]}`);
    }
    for (const line of removed) {
        lines.push(`-${line}`);
    }
    for (const line of added) {
        lines.push(`+${line}`);
    }
    for (let i = a.length - suffix; i < a.length - suffix + contextAfter; i++) {
        lines.push(` ${a[i]}`);
    }

    return lines.join("\n");
}

export function editArgsDiff(args: Record<string, unknown> | null): string {
    if (!args) return "";
    const oldStr = args.oldString;
    const newStr = args.newString;
    if (typeof oldStr !== "string" || typeof newStr !== "string") return "";
    if (oldStr === "" && newStr === "") return "";
    const fileName = typeof args.filePath === "string" ? args.filePath : "file";
    return buildEditDiff(fileName, oldStr, newStr);
}

export function diffStat(diff: string): { added: number; removed: number } {
    let added = 0;
    let removed = 0;
    for (const line of diff.split("\n")) {
        if (line.startsWith("+++") || line.startsWith("---")) continue;
        if (line.startsWith("+")) added++;
        if (line.startsWith("-")) removed++;
    }
    return { added, removed };
}
