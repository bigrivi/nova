/** Token and cost totals for the /stats panel. */
import { request } from "./client.ts";
import type { NovaStats } from "./types.ts";

/**
 * Read the usage totals.
 *
 * Args:
 *   sessionId: Restrict to this session; omit to count every session.
 *   days: Only messages newer than this many days.
 *
 * Returns:
 *   Tokens (exact, from the provider's reports) and an estimated cost.
 */
export async function fetchStats(
    sessionId?: string | null,
    days?: number | null,
): Promise<NovaStats> {
    const params = new URLSearchParams();
    if (sessionId) params.set("session_id", sessionId);
    if (days) params.set("days", String(days));
    const query = params.toString();
    return request<NovaStats>(`/api/stats${query ? `?${query}` : ""}`);
}
