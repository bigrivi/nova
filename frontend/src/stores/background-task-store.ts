import { create } from "zustand";

import type { NovaBackgroundTask } from "../types/nova";

type BackgroundTaskStore = {
    activeSessionId: string | null;
    tasksBySession: Record<string, NovaBackgroundTask[]>;
    tasksById: Record<string, NovaBackgroundTask>;
    error: string | null;
    setActiveSession: (sessionId: string | null) => void;
    replaceTasks: (tasks: NovaBackgroundTask[]) => void;
    updateTask: (task: NovaBackgroundTask) => void;
    setError: (error: string | null) => void;
};

function byNewestFirst(a: NovaBackgroundTask, b: NovaBackgroundTask): number {
    return b.created_at_ms - a.created_at_ms;
}

function upsertTask(
    tasks: NovaBackgroundTask[],
    task: NovaBackgroundTask,
): NovaBackgroundTask[] {
    const index = tasks.findIndex((item) => item.task_id === task.task_id);
    if (index < 0) {
        return [task, ...tasks];
    }
    const next = [...tasks];
    next[index] = task;
    return next;
}

export const useBackgroundTaskStore = create<BackgroundTaskStore>((set) => ({
    activeSessionId: null,
    tasksBySession: {},
    tasksById: {},
    error: null,
    setActiveSession: (activeSessionId) => set({ activeSessionId, error: null }),
    /**
     * Replace everything from the events-stream connect snapshot, which is the
     * server's full truth. Rebuilding also drops tasks the server has evicted.
     */
    replaceTasks: (tasks) =>
        set(() => {
            const tasksById: Record<string, NovaBackgroundTask> = {};
            const tasksBySession: Record<string, NovaBackgroundTask[]> = {};
            for (const task of tasks) {
                tasksById[task.task_id] = task;
                if (task.background) {
                    const list = tasksBySession[task.session_id] ?? [];
                    list.push(task);
                    tasksBySession[task.session_id] = list;
                }
            }
            for (const list of Object.values(tasksBySession)) {
                list.sort(byNewestFirst);
            }
            return { tasksBySession, tasksById, error: null };
        }),
    /**
     * Apply one pushed task update. Only background tasks join the per-session
     * list the panel renders; foreground ones still land in ``tasksById`` so
     * their tool card can show live status.
     */
    updateTask: (task) =>
        set((state) => ({
            tasksById: { ...state.tasksById, [task.task_id]: task },
            tasksBySession: task.background
                ? {
                      ...state.tasksBySession,
                      [task.session_id]: upsertTask(
                          state.tasksBySession[task.session_id] ?? [],
                          task,
                      ),
                  }
                : state.tasksBySession,
        })),
    setError: (error) => set({ error }),
}));
