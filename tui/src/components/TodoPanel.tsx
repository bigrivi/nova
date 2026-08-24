/** Persistent todo progress panel: always shows the latest todo_write state */

import { useTodoStore } from "../stores/todo-store.ts";
import type { TodoItem, TodoStatus } from "../stores/todo-store.ts";

const STATUS_ICON: Record<TodoStatus, string> = {
    completed: "✅",
    in_progress: "🕒",
    pending: "⚪",
    cancelled: "❌",
};

const STATUS_COLOR: Record<TodoStatus, string> = {
    completed: "#6e7681",
    in_progress: "#d29922",
    pending: "#8b949e",
    cancelled: "#6e7681",
};

function summaryLine(todos: TodoItem[]): string {
    const counts = { completed: 0, in_progress: 0, pending: 0, cancelled: 0 };
    for (const todo of todos) {
        counts[todo.status] += 1;
    }
    return `✅ ${counts.completed}  🕒 ${counts.in_progress}  ⚪ ${counts.pending}${
        counts.cancelled ? `  ❌ ${counts.cancelled}` : ""
    }`;
}

export function TodoPanel() {
    const todos = useTodoStore((state) => state.todos);
    if (todos.length === 0) {
        return null;
    }
    return (
        <box
            flexDirection="column"
            border
            borderStyle="rounded"
            borderColor="#30363d"
            paddingX={2}
            paddingY={0}
            marginBottom={0}
        >
            <text fg="#e6edf3">
                Tasks ({summaryLine(todos)})
            </text>
            {todos.map((todo, index) => (
                <text
                    key={`${index}-${todo.content}`}
                    fg={STATUS_COLOR[todo.status]}
                >
                    {`${STATUS_ICON[todo.status]} ${todo.content}${
                        todo.status === "in_progress" ? " …" : ""
                    }`}
                </text>
            ))}
        </box>
    );
}
