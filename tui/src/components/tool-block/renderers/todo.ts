import { RESULT_LIMITS } from "../format/text.ts";
import type { ToolRenderer } from "../types.ts";

type Todo = { content: string; status: string };
type TodoArgs = { todos?: unknown };

function parseArgs(raw: Record<string, unknown> | null): TodoArgs | null {
    if (raw === null) return {};
    return raw;
}

function todosFromArgs(args: TodoArgs): Todo[] | null {
    if (!Array.isArray(args.todos) || args.todos.length === 0) return null;
    const out: Todo[] = [];
    for (const item of args.todos) {
        if (typeof item !== "object" || item === null) continue;
        const content = String((item as { content?: unknown }).content ?? "").trim();
        const status = String((item as { status?: unknown }).status ?? "");
        if (content) out.push({ content, status });
    }
    return out.length > 0 ? out : null;
}

function todosFromOutput(text: string): Todo[] | null {
    const out: Todo[] = [];
    for (const rawLine of text.split("\n")) {
        const line = rawLine.trim();
        if (!line || line.startsWith("##")) continue;
        const match = line.match(/\[(completed|in_progress|pending|cancelled)\]\s*(.+)$/);
        if (match) {
            out.push({ status: match[1]!, content: match[2]!.trim() });
        }
    }
    return out.length > 0 ? out : null;
}

function icon(status: string): string {
    switch (status) {
        case "completed":
            return "[x]";
        case "in_progress":
            return "[>]";
        case "cancelled":
            return "[-]";
        default:
            return "[ ]";
    }
}

export const todoRenderer: ToolRenderer<TodoArgs> = {
    parseArgs,
    verbs: { running: "Updating", done: "Updated", error: "Failed to update" },
    subject: (args) => {
        const todos = todosFromArgs(args);
        return todos ? `${todos.length} todos` : "todos";
    },
    meta: (ctx) => {
        const todos = todosFromArgs(ctx.args) ?? todosFromOutput(ctx.outputText);
        if (!todos || todos.length === 0) return undefined;
        const done = todos.filter((todo) => todo.status === "completed").length;
        return `${done}/${todos.length}`;
    },
    result: (ctx) => {
        const todos = todosFromArgs(ctx.args) ?? todosFromOutput(ctx.outputText);
        if (!todos || todos.length === 0) return { kind: "none" };
        return {
            kind: "lines",
            lines: todos.map((todo) => `${icon(todo.status)} ${todo.content}`),
            hiddenAt: "bottom",
            limit: RESULT_LIMITS.todos,
        };
    },
    blockedTitle: () => "Waiting for approval — todo_write",
};
