/** Background tasks: what the agent started and left running.
 *
 *  Own module rather than another block in `nova-api.ts`: the task routes have
 *  their own session/ownership rules (every call carries the session id) and
 *  nothing else in the client needs them.
 */
import { type JsonResponse, jsonInit, request } from "./client.ts";
import type { NovaTask } from "./types.ts";

/** Tasks retained for this session, oldest first as the backend returns them. */
export async function listTasks(sessionId: string): Promise<NovaTask[]> {
    const payload = await request<JsonResponse<NovaTask>>(
        `/api/tasks?session_id=${encodeURIComponent(sessionId)}`,
    );
    return payload.items;
}

/** The bounded output tail of one task, for the detail view. */
export async function getTaskLogs(
    taskId: string,
    sessionId: string,
): Promise<string> {
    const payload = await request<{ output: string }>(
        `/api/tasks/${taskId}/logs?session_id=${encodeURIComponent(sessionId)}`,
    );
    return payload.output;
}

/** Cancel a running task. Throws when the task is unknown or already finished. */
export async function cancelTask(
    taskId: string,
    sessionId: string,
): Promise<void> {
    await request<{ status: string }>(
        `/api/tasks/${taskId}/cancel`,
        jsonInit("POST", { session_id: sessionId }),
    );
}
