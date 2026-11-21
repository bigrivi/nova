/** The agent's todo list: what it is working through right now.
 *
 *  The transcript shows todo_write calls as they happen; this is the one place
 *  the whole list is visible at once, which is what makes it worth a panel.
 */
import { TextAttributes } from "@opentui/core";
import { useTheme } from "../../context/theme.tsx";
import { useChatStore } from "../../stores/chat-store.ts";
import { useTodos, type TodoItem } from "../../stores/todo-store.ts";
import { PanelHeading } from "./PanelHeading.tsx";

const GLYPH: Record<TodoItem["status"], string> = {
    pending: "[ ]",
    in_progress: "[•]",
    completed: "[✓]",
    cancelled: "[-]",
};

export function TodoPanel() {
    const theme = useTheme();
    const sessionId = useChatStore((state) => state.sessionId);
    const todos = useTodos(sessionId);

    if (todos.length === 0) return null;

    const done = todos.filter(
        (todo) => todo.status === "completed" || todo.status === "cancelled",
    ).length;

    return (
        <box flexDirection="column" flexShrink={0}>
            <PanelHeading label="Todos" detail={`(${done}/${todos.length})`} />
            {todos.map((todo) => {
                const fg =
                    todo.status === "in_progress"
                        ? theme.feedback.running
                        : todo.status === "cancelled"
                          ? theme.text.faint
                          : theme.text.muted;
                return (
                    <box
                        key={`${todo.status}:${todo.content}`}
                        flexDirection="row"
                        gap={1}
                    >
                        <text
                            flexShrink={0}
                            fg={fg}
                            content={GLYPH[todo.status]}
                        />
                        <text
                            fg={fg}
                            content={todo.content}
                            wrapMode="none"
                            attributes={
                                todo.status === "cancelled"
                                    ? TextAttributes.STRIKETHROUGH
                                    : undefined
                            }
                        />
                    </box>
                );
            })}
        </box>
    );
}
