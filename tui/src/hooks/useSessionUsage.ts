/** This session's token and cost totals.
 *
 *  Read once per session and kept in a bucket: the totals only move when the
 *  agent answers, so a tab switch reads the cached numbers. The stream's turn
 *  end refreshes the bucket for whichever tab finished, active or not.
 */
import { useEffect } from "react";

import type { NovaStats } from "../api/types.ts";
import { refreshSessionStats } from "../lib/session-usage.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useSessionStats, useUsageStore } from "../stores/usage-store.ts";

export function useSessionUsage(): NovaStats | null {
    const sessionId = useChatStore((state) => state.sessionId);
    const stats = useSessionStats(sessionId);

    // A session seen for the first time has no bucket yet; one read fills it.
    useEffect(() => {
        if (
            sessionId &&
            useUsageStore.getState().byId[sessionId] === undefined
        ) {
            refreshSessionStats(sessionId);
        }
    }, [sessionId]);

    return stats;
}
