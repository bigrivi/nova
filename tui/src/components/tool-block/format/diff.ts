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
