/**
 * View models for the three tools that get a dedicated card.
 *
 * Ported from the web renderers: `file-mutation-tool.tsx`,
 * `code-run-tool.tsx` and `delegate-tool.tsx`. Pure functions only; the
 * components own layout.
 */
import type { ToolPart } from "../state/chat";

export type FileMutationView = {
    kind: "file-mutation";
    /** "Edited notes.md", or just "Editing" while there is no path yet. */
    label: string;
    path: string | null;
    headline: string;
    diff: string | null;
    plain: string | null;
};

export type CodeRunView = {
    kind: "code-run";
    label: string;
    summary: string;
    code: string;
    description: string;
    output: string;
    backgroundTaskId: string | null;
};

export type DelegateView = {
    kind: "delegate";
    label: string;
    task: string;
    output: string;
};

export type ToolView = FileMutationView | CodeRunView | DelegateView;

const TASK_PREVIEW_LIMIT = 160;

function parseJsonRecord(text: string): Record<string, unknown> | null {
    const trimmed = text.trim();
    if (!trimmed) {
        return null;
    }
    try {
        const parsed: unknown = JSON.parse(trimmed);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : null;
    } catch {
        return null;
    }
}

/** Tool arguments arrive as accumulated JSON text and may still be partial. */
export function parseToolInput(inputText: string): Record<string, unknown> {
    return parseJsonRecord(inputText) ?? {};
}

function readString(record: Record<string, unknown>, key: string): string {
    const value = record[key];
    return typeof value === "string" ? value : "";
}

/**
 * Unwrap a tool result into the text a card shows.
 *
 * A streamed result is already parsed (`{content}` / `{background_task}`),
 * while a history result is the same shape re-serialized, so one unwrap
 * covers both.
 */
export function readToolResult(outputText: string): {
    text: string;
    raw: Record<string, unknown> | null;
} {
    const trimmed = outputText.trim();
    if (!trimmed) {
        return { text: "", raw: null };
    }
    const raw = parseJsonRecord(trimmed);
    if (!raw) {
        return { text: outputText, raw: null };
    }
    if (typeof raw.content === "string") {
        return { text: raw.content, raw };
    }
    if (raw.background_task && typeof raw.background_task === "object") {
        const message = typeof raw.message === "string" ? raw.message : "";
        return { text: message, raw };
    }
    return { text: outputText, raw };
}

function backgroundTaskId(
    raw: Record<string, unknown> | null,
): string | null {
    const task = raw?.background_task;
    if (!task || typeof task !== "object") {
        return null;
    }
    const id = (task as Record<string, unknown>).task_id;
    return typeof id === "string" && id ? id : null;
}

function baseName(path: string): string {
    const parts = path.split(/[/\\]/);
    return parts[parts.length - 1] || path;
}

/** `"Changes applied to x:\n\n--- ..."` -> headline plus unified diff. */
export function splitMutationOutput(text: string): {
    headline: string;
    diff: string | null;
} {
    const divider = text.indexOf("\n\n--- ");
    if (divider < 0) {
        return { headline: text, diff: null };
    }
    return {
        headline: text.slice(0, divider).trim(),
        diff: text.slice(divider + 2).trim(),
    };
}

/** Added and removed line counts, ignoring the `---`/`+++` file headers. */
export function countDiffLines(diff: string): {
    added: number;
    removed: number;
} {
    let added = 0;
    let removed = 0;
    for (const line of diff.split("\n")) {
        if (line.startsWith("+") && !line.startsWith("+++ ")) {
            added += 1;
        } else if (line.startsWith("-") && !line.startsWith("--- ")) {
            removed += 1;
        }
    }
    return { added, removed };
}

function fileMutationView(
    toolName: string,
    inputText: string,
    outputText: string,
    settled: boolean,
    errored: boolean,
): FileMutationView {
    const args = parseToolInput(inputText);
    const path = readString(args, "filePath").trim() || null;
    const { text } = readToolResult(outputText);
    const { headline, diff } = text
        ? splitMutationOutput(text)
        : { headline: "", diff: null };
    const isEdit = toolName === "edit";
    const verb = isEdit
        ? settled && !errored
            ? "Edited"
            : "Editing"
        : settled && !errored
          ? "Wrote"
          : "Writing";
    const name = path ? baseName(path) : null;

    return {
        kind: "file-mutation",
        label: name ? `${verb} ${name}` : verb,
        path,
        headline: diff ? headline : "",
        diff,
        plain: diff || !text.trim() ? null : text.trim(),
    };
}

function codeRunView(
    inputText: string,
    outputText: string,
): CodeRunView {
    const args = parseToolInput(inputText);
    const { text, raw } = readToolResult(outputText);
    return {
        kind: "code-run",
        label: "code_run",
        summary: readString(args, "description"),
        code: readString(args, "code"),
        description: readString(args, "description"),
        output: text.trim(),
        backgroundTaskId: backgroundTaskId(raw),
    };
}

function delegateView(
    inputText: string,
    outputText: string,
): DelegateView {
    const args = parseToolInput(inputText);
    const target = readString(args, "target").trim();
    const task = readString(args, "task").replace(/\s+/g, " ").trim();
    const { text } = readToolResult(outputText);
    return {
        kind: "delegate",
        label: target ? `Delegated to ${target}` : "Delegate to agent",
        task:
            task.length > TASK_PREVIEW_LIMIT
                ? `${task.slice(0, TASK_PREVIEW_LIMIT - 1)}…`
                : task,
        output: text.trim(),
    };
}

/**
 * Pick the dedicated card for a tool call, or null for the generic row.
 *
 * @param part Tool call with accumulated argument and result text.
 * @returns The card's view model, or null when no dedicated view applies.
 */
export function buildToolView(part: ToolPart): ToolView | null {
    const toolName = (part.toolName ?? "").trim().toLowerCase();
    const settled = part.status !== "running";
    const errored = part.status === "error";

    if (toolName === "edit" || toolName === "write") {
        return fileMutationView(
            toolName,
            part.inputText,
            part.outputText,
            settled,
            errored,
        );
    }
    if (toolName === "code_run") {
        return codeRunView(part.inputText, part.outputText);
    }
    if (toolName === "delegate_to_agent") {
        return delegateView(part.inputText, part.outputText);
    }
    return null;
}
