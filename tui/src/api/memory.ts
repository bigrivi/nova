/** Memories: what the agent chose to keep, and what it can be made to forget. */
import { type JsonResponse, request } from "./client.ts";
import type { NovaMemory } from "./types.ts";

/** Memories for a session, or the most recent ones across scopes. */
export async function listMemories(options: {
    sessionId?: string | null;
    query?: string | null;
} = {}): Promise<NovaMemory[]> {
    const params = new URLSearchParams();
    if (options.query?.trim()) params.set("q", options.query.trim());
    if (options.sessionId) params.set("session_id", options.sessionId);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    const payload = await request<JsonResponse<NovaMemory>>(
        `/api/memories${suffix}`,
    );
    return payload.items;
}

/** Drop one memory. Throws when it is already gone. */
export async function deleteMemory(memoryId: string): Promise<void> {
    await request<{ status: string }>(
        `/api/memories/${encodeURIComponent(memoryId)}`,
        { method: "DELETE" },
    );
}
