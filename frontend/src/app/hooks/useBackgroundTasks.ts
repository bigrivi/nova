import { useEffect } from "react";

import { DRAFT_THREAD_ID } from "../../lib/nova-constants";
import { listBackgroundTasks } from "../../lib/nova-api";
import { useBackgroundTaskStore } from "../../stores/background-task-store";

const TASK_POLL_INTERVAL_MS = 2000;

export function useBackgroundTasks(sessionId: string, isRunning: boolean): void {
    const setActiveSession = useBackgroundTaskStore((state) => state.setActiveSession);
    const setTasks = useBackgroundTaskStore((state) => state.setTasks);
    const setError = useBackgroundTaskStore((state) => state.setError);

    useEffect(() => {
        if (!sessionId || sessionId === DRAFT_THREAD_ID) {
            setActiveSession(null);
            return;
        }

        setActiveSession(sessionId);
        let disposed = false;
        let timer: number | undefined;

        const poll = async () => {
            try {
                const tasks = await listBackgroundTasks(sessionId);
                if (!disposed) {
                    setTasks(sessionId, tasks);
                    const hasActiveTasks = tasks.some(
                        (task) => task.status === "queued" || task.status === "running",
                    );
                    if (hasActiveTasks || isRunning) {
                        timer = window.setTimeout(poll, TASK_POLL_INTERVAL_MS);
                    }
                }
            } catch (error) {
                if (!disposed) {
                    setError(
                        error instanceof Error
                            ? error.message
                            : "Unable to load background tasks",
                    );
                    timer = window.setTimeout(poll, TASK_POLL_INTERVAL_MS);
                }
            }
        };

        void poll();
        return () => {
            disposed = true;
            if (timer !== undefined) window.clearTimeout(timer);
        };
    }, [isRunning, sessionId, setActiveSession, setError, setTasks]);
}
