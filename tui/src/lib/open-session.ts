/** Open a saved session in the current screen: fetch its history and show it.
 *
 *  Shared by the sessions list and `/fork`, so the two cannot drift on what
 *  "open a session" means (which ids get reset, what happens on failure).
 */
import { listMessages } from "../api/nova-api.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { recordsToMessages } from "../utils/history.ts";

/** Load *sessionId* into the transcript. Throws when the fetch fails. */
export async function openSession(sessionId: string): Promise<void> {
    const records = await listMessages(sessionId);
    useChatStore
        .getState()
        .loadHistory(sessionId, recordsToMessages(records));
}
