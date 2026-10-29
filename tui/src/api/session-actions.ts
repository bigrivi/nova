/** Session actions that are not a chat turn: compaction, and what it costs.
 *
 *  Separate from `nova-api.ts` because these mutate the session history rather
 *  than the catalog, and the caller has to reload what they changed.
 */
import { jsonInit, request } from "./client.ts";

/** Compact the session now. `compacted: false` means there was nothing to do. */
export async function compactSession(
    sessionId: string,
): Promise<{ compacted: boolean }> {
    return request<{ compacted: boolean }>(
        `/api/sessions/${sessionId}/compact`,
        { method: "POST" },
    );
}

/** Copy the conversation into a new session; returns the copy's id. */
export async function forkSession(
    sessionId: string,
    messageId?: string | null,
): Promise<{ session_id: string; title: string; messages: number }> {
    return request<{ session_id: string; title: string; messages: number }>(
        `/api/sessions/${sessionId}/fork`,
        jsonInit("POST", { message_id: messageId || undefined }),
    );
}
