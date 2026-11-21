/** Read a session's context meter once, then keep it in its bucket.
 *
 *  The stream carries the live part; this covers an idle or restored session
 *  the first time it is shown, so switching back never needs the request.
 */
import { getSessionContext } from "../api/nova-api.ts";
import { useCtxStore } from "../stores/ctx-store.ts";

const inFlight = new Map<string, Promise<void>>();

export function ensureSessionContext(sessionId: string): void {
    if (useCtxStore.getState().byId[sessionId] || inFlight.has(sessionId)) {
        return;
    }
    const promise = getSessionContext(sessionId)
        .then((ctx) => {
            useCtxStore
                .getState()
                .setCtx(sessionId, ctx.used, ctx.limit, ctx.percent);
        })
        .catch(() => {})
        .finally(() => {
            inFlight.delete(sessionId);
        });
    inFlight.set(sessionId, promise);
}
