/** Fork the open conversation and switch into the copy.
 *
 *  Same shape as Claude Code's `/branch`: the origin is left intact and the user
 *  lands in the branch, so trying a different direction never costs the
 *  conversation that was already there.
 */
import { forkSession } from "../api/session-actions.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { openSession } from "./open-session.ts";

/** Returns the line to show the user; throws when the backend refuses. */
export async function forkOpenSession(): Promise<string> {
    const { sessionId } = useChatStore.getState();
    if (!sessionId) return "Nothing to fork: no open session";

    const result = await forkSession(sessionId);
    await openSession(result.session_id);
    return `Forked into “${result.title}” (${result.messages} message(s))`;
}
