export type BackgroundTaskReference = {
    taskId: string | null;
    status: string | null;
    message: string | null;
};

function parseObject(value: unknown): Record<string, unknown> | null {
    if (typeof value === "string") {
        try {
            const parsed: unknown = JSON.parse(value);
            return parsed && typeof parsed === "object" && !Array.isArray(parsed)
                ? (parsed as Record<string, unknown>)
                : null;
        } catch {
            return null;
        }
    }
    return value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : null;
}

function readTaskEnvelope(result: unknown): BackgroundTaskReference | null {
    const output = parseObject(result);
    const candidate = output?.background_task;
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
        return null;
    }
    const task = candidate as Record<string, unknown>;
    return {
        taskId: typeof task.task_id === "string" ? task.task_id : null,
        status: typeof task.status === "string" ? task.status : null,
        message: typeof output?.message === "string" ? output.message : null,
    };
}

export function readBackgroundTaskReference(
    argsText: string | undefined,
    result: unknown,
): BackgroundTaskReference | null {
    const envelope = readTaskEnvelope(result);
    if (envelope) return envelope;

    const args = parseObject(argsText);
    if (result != null || args?.run_in_background !== true) return null;
    return { taskId: null, status: null, message: null };
}

export function readBackgroundTaskEnvelope(
    result: unknown,
): BackgroundTaskReference | null {
    return readTaskEnvelope(result);
}

const LIVE_TASK_STATUSES = new Set(["queued", "running"]);

/**
 * Whether any task still needs watching.
 *
 * Only queued/running tasks qualify. Terminal tasks stay queryable for a while
 * (retention), so counting them would keep a poller alive for no reason.
 *
 * @param tasks Task records as returned by ``GET /api/tasks``
 * @returns True while at least one task has not finished
 */
export function hasLiveTasks(tasks: readonly { status: string }[]): boolean {
    return tasks.some((task) => LIVE_TASK_STATUSES.has(task.status));
}
