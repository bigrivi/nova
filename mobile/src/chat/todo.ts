/** `todo_write` arguments, normalized for the progress panel. */

export type TodoStatus =
    | "pending"
    | "in_progress"
    | "completed"
    | "cancelled";

export type TodoItem = {
    content: string;
    status: TodoStatus;
    priority?: string;
};

function normalizeStatus(value: unknown): TodoStatus {
    return value === "in_progress" ||
        value === "completed" ||
        value === "cancelled"
        ? value
        : "pending";
}

export function parseTodos(input: unknown): TodoItem[] {
    let raw: unknown = input;
    if (typeof raw === "string") {
        try {
            raw = JSON.parse(raw) as unknown;
        } catch {
            return [];
        }
    }
    const list = Array.isArray(raw)
        ? raw
        : raw && typeof raw === "object"
          ? (raw as { todos?: unknown }).todos
          : null;
    if (!Array.isArray(list)) {
        return [];
    }
    return list
        .filter(
            (item): item is Record<string, unknown> =>
                !!item && typeof item === "object",
        )
        .map((item) => ({
            content: String(item.content ?? "").trim(),
            status: normalizeStatus(item.status),
            ...(item.priority !== undefined
                ? { priority: String(item.priority) }
                : {}),
        }))
        .filter((item) => item.content.length > 0);
}
