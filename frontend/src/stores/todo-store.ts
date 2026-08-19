import { create } from "zustand";

export type TodoStatus =
    | "pending"
    | "in_progress"
    | "completed"
    | "cancelled";

export type TodoItem = {
    content: string;
    status: string;
    priority?: string;
};

type TodoPanelData = {
    todos: TodoItem[];
    updatedAt: number;
};

type TodoStore = {
    active: TodoPanelData | null;
    setActive: (input: unknown) => void;
    clear: () => void;
};

function parseTodos(args: unknown): TodoItem[] {
    let raw: unknown = args;
    if (typeof raw === "string") {
        try {
            raw = JSON.parse(raw);
        } catch {
            return [];
        }
    }

    const list = Array.isArray(raw)
        ? raw
        : raw && typeof raw === "object"
          ? (raw as { todos?: unknown }).todos
          : null;

    if (!Array.isArray(list)) return [];
    return list.filter(
        (t): t is TodoItem => !!t && typeof t === "object",
    );
}

export const useTodoStore = create<TodoStore>((set) => ({
    active: null,
    setActive: (input) =>
        set({ active: { todos: parseTodos(input), updatedAt: Date.now() } }),
    clear: () => set({ active: null }),
}));