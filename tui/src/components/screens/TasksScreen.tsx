/** Background tasks screen: what the agent left running, with a live refresh */
import { useEffect, useState } from "react";
import { listTasks } from "../../api/tasks.ts";
import type { NovaTask } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { taskLine } from "../../lib/task-format.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { TaskDetail } from "./TaskDetail.tsx";

/** Long enough to catch a status change, short enough to feel live. */
const REFRESH_MS = 2000;

function sortForDisplay(tasks: NovaTask[]): NovaTask[] {
    // Running first, then most recent: the task the user came to look at is at
    // the top without having to read the whole list.
    const rank = (task: NovaTask): number =>
        task.status === "running" ? 0 : task.status === "queued" ? 1 : 2;
    return [...tasks].sort(
        (left, right) =>
            rank(left) - rank(right) || right.created_at_ms - left.created_at_ms,
    );
}

export function TasksScreen() {
    const sessionId = useChatStore((state) => state.sessionId);
    const [selected, setSelected] = useState<NovaTask | null>(null);
    const [tasks, setTasks] = useState<NovaTask[]>([]);
    const [error, setError] = useState("");
    const [ready, setReady] = useState(false);

    // Own polling rather than `useListScreen`: its reload clears the list for a
    // render, and a panel that flashes every two seconds is worse than a stale
    // row. Errors keep the last good list on screen.
    useEffect(() => {
        if (!sessionId) {
            setReady(true);
            return;
        }
        let cancelled = false;
        const load = (): void => {
            void listTasks(sessionId)
                .then((items) => {
                    if (cancelled) return;
                    setTasks(items);
                    setError("");
                    setReady(true);
                })
                .catch((err: unknown) => {
                    if (cancelled) return;
                    setError(err instanceof Error ? err.message : String(err));
                    setReady(true);
                });
        };
        load();
        const timer = setInterval(load, REFRESH_MS);
        return () => {
            cancelled = true;
            clearInterval(timer);
        };
    }, [sessionId]);

    if (!ready) {
        return <ScreenLoading message={error || "Loading tasks..."} />;
    }

    if (selected && sessionId) {
        return (
            <TaskDetail
                task={selected}
                sessionId={sessionId}
                onBack={() => setSelected(null)}
            />
        );
    }

    const ordered = sortForDisplay(tasks);

    return (
        <SearchableList
            title="Background tasks"
            items={ordered.map((task) => ({
                label: taskLine(task),
                value: task.task_id,
            }))}
            onSelect={(value) => {
                const task = ordered.find((entry) => entry.task_id === value);
                if (task) setSelected(task);
            }}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no background tasks in this session"}
        />
    );
}
