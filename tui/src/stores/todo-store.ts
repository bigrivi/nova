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
    todos: TodoItem[];
    setTodos: (todos: TodoItem[]) => void;
    clear: () => void;
};

export const useTodoStore = create<TodoState>((set) => ({
    todos: [],
    setTodos: (todos) => set({ todos }),
    clear: () => set({ todos: [] }),
}));
