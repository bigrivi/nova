/** This session's token and cost totals.
 *
 *  Read when the panel opens and again when a turn ends: the totals only move
 *  when the agent answers, so there is nothing to poll for. Same rule the web
 *  UI follows for context usage: the stream carries the live part, one REST
 *  read covers the rest.
 */
import { useEffect, useRef, useState } from "react";

import { fetchStats } from "../api/stats.ts";
import type { NovaStats } from "../api/types.ts";
import { logWarn } from "../lib/errors.ts";
import { useChatStore } from "../stores/chat-store.ts";

export function useSessionUsage(): NovaStats | null {
    const sessionId = useChatStore((state) => state.sessionId);
    const isStreaming = useChatStore((state) => state.isStreaming);
    const [stats, setStats] = useState<NovaStats | null>(null);
    const [reloadKey, setReloadKey] = useState(0);
    const streaming = useRef(false);

    // A turn that just finished changed the totals; a turn that just started
    // did not, so only the falling edge refetches.
    useEffect(() => {
        if (streaming.current && !isStreaming) {
            setReloadKey((value) => value + 1);
        }
        streaming.current = isStreaming;
    }, [isStreaming]);

    useEffect(() => {
        if (!sessionId) {
            setStats(null);
            return;
        }
        let cancelled = false;
        void fetchStats(sessionId)
            .then((next) => {
                if (!cancelled) {
                    setStats(next);
                }
            })
            .catch((err: unknown) => {
                logWarn("loading session usage failed", err);
            });
        return () => {
            cancelled = true;
        };
    }, [sessionId, reloadKey]);

    return stats;
}
