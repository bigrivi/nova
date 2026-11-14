/** The agent's todo list: what it is working through right now.
 *
 *  The transcript shows todo_write calls as they happen; this is the one place
 *  the whole list is visible at once, which is what makes it worth a panel.
 */
import { useTheme } from "../../context/theme.tsx";
import { useTodoStore, type TodoItem } from "../../stores/todo-store.ts";
import { PanelHeading } from "./PanelHeading.tsx";

const GLYPH: Record<TodoItem["status"], string> = {
    pending: "○",
    in_progress: "◐",
    completed: "✓",
    cancelled: "✗",
};

export function TodoPanel() {
    const theme = useTheme();
    const todos = useTodoStore((state) => state.todos);

    if (todos.length === 0) return null;

    const done = todos.filter(
        (todo) => todo.status === "completed" || todo.status === "cancelled",
    ).length;

    return (
        <box flexDirection="column" flexShrink={0}>
            <PanelHeading label="Todos" detail={`(${done}/${todos.length})`} />
            {todos.map((todo) => {
                const settled =
                    todo.status === "completed" || todo.status === "cancelled";
                return (
                    <box
                        key={`${todo.status}:${todo.content}`}
                        flexDirection="row"
                        gap={1}
                    >
                        <text
                            flexShrink={0}
                            fg={
                                todo.status === "in_progress"
                                    ? theme.primary.base
                                    : settled
                                      ? theme.feedback.success
                                      : theme.text.faint
                            }
                            content={GLYPH[todo.status]}
                        />
                        <text
                            fg={settled ? theme.text.faint : theme.text.muted}
                            content={todo.content}
                            wrapMode="none"
                        />
                    </box>
                );
            })}
        </box>
    );
}
