/** Todo list state: the latest todo_write payload (zustand) */

import { create } from "zustand";

export type TodoStatus =
    | "pending"
    | "in_progress"
    | "completed"
    | "cancelled";

export type TodoItem = {
    content: string;
    status: TodoStatus;
    priority: "high" | "medium" | "low";
};

export function parseTodos(input: unknown): TodoItem[] {
    const todos = (input as { todos?: unknown } | null | undefined)?.todos;
    if (!Array.isArray(todos)) {
        return [];
    }
    const valid: TodoItem[] = [];
    for (const item of todos) {
        if (
            typeof item !== "object" ||
            item === null ||
            typeof (item as { content?: unknown }).content !== "string"
        ) {
            continue
        }
        const entry = item as { content: string; status?: unknown; priority?: unknown };
        valid.push({
            content: entry.content,
            status: parseStatus(entry.status),
            priority: parsePriority(entry.priority),
        });
    }
    return valid;
}

function parseStatus(value: unknown): TodoStatus {
    return value === "in_progress" ||
        value === "completed" ||
        value === "cancelled"
        ? value
        : "pending";
}

function parsePriority(value: unknown): "high" | "medium" | "low" {
    return value === "high" || value === "medium"
        ? value
        : "low";
}

type TodoState = {
    byId: Record<string, TodoItem[]>;
    setTodos: (sessionId: string, todos: TodoItem[]) => void;
    clear: (sessionId?: string) => void;
};

const NO_TODOS: TodoItem[] = [];

export const useTodoStore = create<TodoState>((set) => ({
    byId: {},
    setTodos: (sessionId, todos) =>
        set((state) => ({ byId: { ...state.byId, [sessionId]: todos } })),
    clear: (sessionId) =>
        set((state) => {
            if (sessionId === undefined) {
                return { byId: {} };
            }
            if (!(sessionId in state.byId)) {
                return state;
            }
            const byId = { ...state.byId };
            delete byId[sessionId];
            return { byId };
        }),
}));

/** One session's list; a tab switch swaps the list rather than mixing them. */
export function useTodos(sessionId: string | null): TodoItem[] {
    return useTodoStore((state) =>
        sessionId === null ? NO_TODOS : (state.byId[sessionId] ?? NO_TODOS),
    );
}
