import { create } from "zustand";

import type { NovaBackgroundTask } from "../types/nova";

type BackgroundTaskStore = {
    activeSessionId: string | null;
    tasksBySession: Record<string, NovaBackgroundTask[]>;
    tasksById: Record<string, NovaBackgroundTask>;
    error: string | null;
    setActiveSession: (sessionId: string | null) => void;
    setTasks: (sessionId: string, tasks: NovaBackgroundTask[]) => void;
    updateTask: (task: NovaBackgroundTask) => void;
    setError: (error: string | null) => void;
};

export const useBackgroundTaskStore = create<BackgroundTaskStore>((set) => ({
    activeSessionId: null,
    tasksBySession: {},
    tasksById: {},
    error: null,
    setActiveSession: (activeSessionId) => set({ activeSessionId, error: null }),
    setTasks: (sessionId, tasks) =>
        set((state) => ({
            tasksBySession: { ...state.tasksBySession, [sessionId]: tasks },
            tasksById: {
                ...state.tasksById,
                ...Object.fromEntries(tasks.map((task) => [task.task_id, task])),
            },
            error: null,
        })),
    updateTask: (task) =>
        set((state) => {
            const sessionTasks = state.tasksBySession[task.session_id] ?? [];
            const existingIndex = sessionTasks.findIndex(
                (item) => item.task_id === task.task_id,
            );
            const updatedTasks = [...sessionTasks];
            if (existingIndex >= 0) {
                updatedTasks[existingIndex] = task;
            } else {
                updatedTasks.unshift(task);
            }
            return {
                tasksBySession: {
                    ...state.tasksBySession,
                    [task.session_id]: updatedTasks,
                },
                tasksById: { ...state.tasksById, [task.task_id]: task },
            };
        }),
    setError: (error) => set({ error }),
}));
