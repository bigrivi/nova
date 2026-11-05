/** Background tasks pushed over `/api/events`, grouped by session. */
import { create } from "zustand";

import type { NovaBackgroundTask } from "../api/types";

type TasksState = {
    byId: Record<string, NovaBackgroundTask>;
    bySession: Record<string, NovaBackgroundTask[]>;
    replace: (tasks: NovaBackgroundTask[]) => void;
    update: (task: NovaBackgroundTask) => void;
    reset: () => void;
};

function newestFirst(
    left: NovaBackgroundTask,
    right: NovaBackgroundTask,
): number {
    return right.created_at_ms - left.created_at_ms;
}

function upsert(
    tasks: readonly NovaBackgroundTask[],
    task: NovaBackgroundTask,
): NovaBackgroundTask[] {
    const index = tasks.findIndex((item) => item.task_id === task.task_id);
    if (index === -1) {
        return [task, ...tasks];
    }
    const next = [...tasks];
    next[index] = task;
    return next;
}

export const useTasks = create<TasksState>((set) => ({
    byId: {},
    bySession: {},
    replace: (tasks) =>
        set(() => {
            const byId: Record<string, NovaBackgroundTask> = {};
            const bySession: Record<string, NovaBackgroundTask[]> = {};
            for (const task of tasks) {
                byId[task.task_id] = task;
                if (task.background) {
                    const list = bySession[task.session_id] ?? [];
                    list.push(task);
                    bySession[task.session_id] = list;
                }
            }
            for (const list of Object.values(bySession)) {
                list.sort(newestFirst);
            }
            return { byId, bySession };
        }),
    update: (task) =>
        set((state) => ({
            byId: { ...state.byId, [task.task_id]: task },
            bySession: task.background
                ? {
                      ...state.bySession,
                      [task.session_id]: upsert(
                          state.bySession[task.session_id] ?? [],
                          task,
                      ),
                  }
                : state.bySession,
        })),
    reset: () => set({ byId: {}, bySession: {} }),
}));
