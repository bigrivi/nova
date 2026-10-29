/** Detail view for one background task: what it was, how long, and its tail */
import { useKeyboard } from "@opentui/react";
import { useEffect, useState } from "react";
import { cancelTask, getTaskLogs } from "../../api/tasks.ts";
import type { NovaTask } from "../../api/types.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { formatDuration, isCancellable, taskDurationMs, taskStatusLabel } from "../../lib/task-format.ts";
import { ScreenPanel } from "./ScreenPanel.tsx";

const TAIL_LINES = 12;

export function TaskDetail({
    task,
    sessionId,
    onBack,
}: {
    task: NovaTask;
    sessionId: string;
    onBack: () => void;
}) {
    const theme = useTheme();
    const [output, setOutput] = useState<string>("");
    const [error, setError] = useState<string>("");

    useEffect(() => {
        let cancelled = false;
        void getTaskLogs(task.task_id, sessionId)
            .then((text) => {
                if (!cancelled) setOutput(text);
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : String(err));
                }
            });
        return () => {
            cancelled = true;
        };
    }, [task.task_id, sessionId]);

    useKeyboard((key) => {
        if (key.name === "escape" || key.name === "q") {
            onBack();
            return;
        }
        if (key.name === "c" && isCancellable(task)) {
            void cancelTask(task.task_id, sessionId)
                .then(() => {
                    useToastStore.getState().show("Task cancelled", 3000);
                    onBack();
                })
                .catch((err: unknown) => {
                    useToastStore
                        .getState()
                        .show(
                            `Cancel failed: ${err instanceof Error ? err.message : String(err)}`,
                            4000,
                        );
                });
        }
    });

    const tail = output.trim().split("\n").slice(-TAIL_LINES).join("\n");

    return (
        <ScreenPanel width="80%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.text.base} content={task.label || task.kind} />
                <text
                    fg={theme.text.muted}
                    content={`${taskStatusLabel(task.status)} · ${formatDuration(
                        taskDurationMs(task),
                    )} · ${task.kind}${task.exit_code === null ? "" : ` · exit ${task.exit_code}`}`}
                />
                {error ? (
                    <text fg={theme.feedback.error} content={error} />
                ) : null}
                {task.error ? (
                    <text fg={theme.feedback.error} content={task.error} />
                ) : null}
                <box flexDirection="column">
                    {tail ? (
                        tail.split("\n").map((line, index) => (
                            <text
                                key={`${index}-${line}`}
                                fg={theme.text.muted}
                                content={line}
                            />
                        ))
                    ) : (
                        <text fg={theme.text.faint} content="(no output yet)" />
                    )}
                </box>
                <text
                    fg={theme.text.faint}
                    content={
                        isCancellable(task)
                            ? "c cancel · esc back"
                            : "esc back"
                    }
                />
            </box>
        </ScreenPanel>
    );
}
