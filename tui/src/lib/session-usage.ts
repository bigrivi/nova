/** Read a session's spend and keep it in that session's bucket.
 *
 *  Called when a session is first shown and when any turn ends, including a
 *  background tab's, so a switch never needs its own request.
 */
import { fetchStats } from "../api/stats.ts";
import { useUsageStore } from "../stores/usage-store.ts";
import { logWarn } from "./errors.ts";

const inFlight = new Map<string, Promise<void>>();
const rerun = new Set<string>();

export function refreshSessionStats(sessionId: string): void {
    if (inFlight.has(sessionId)) {
        // A turn ended while the previous read was still out; read again once
        // it lands rather than keeping the pre-turn totals.
        rerun.add(sessionId);
        return;
    }
    const promise = fetchStats(sessionId)
        .then((stats) => {
            useUsageStore.getState().setStats(sessionId, stats);
        })
        .catch((err: unknown) => {
            logWarn("loading session usage failed", err);
        })
        .finally(() => {
            inFlight.delete(sessionId);
            if (rerun.delete(sessionId)) {
                refreshSessionStats(sessionId);
            }
        });
    inFlight.set(sessionId, promise);
}
