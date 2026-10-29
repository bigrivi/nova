/** Compact the open session and reload what compaction rewrote.
 *
 *  Both halves belong together: the summary replaces messages, so a client that
 *  ran the call but kept its own copy would show a transcript the backend no
 *  longer has, and a context meter that still reads the pre-compaction count.
 */
import { compactSession } from "../api/session-actions.ts";
import { getSessionContext, listMessages } from "../api/nova-api.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { recordsToMessages } from "../utils/history.ts";

/** Returns the line to show the user; throws when the backend refuses. */
export async function compactOpenSession(): Promise<string> {
    const { sessionId } = useChatStore.getState();
    if (!sessionId) return "Nothing to compact: no open session";

    const result = await compactSession(sessionId);
    if (!result.compacted) return "Nothing to compact";

    const records = await listMessages(sessionId);
    useChatStore
        .getState()
        .loadHistory(sessionId, recordsToMessages(records));

    const ctx = await getSessionContext(sessionId);
    useCtxStore.getState().setCtx(ctx.used, ctx.limit, ctx.percent);
    return "Context compacted";
}
