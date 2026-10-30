/** Open a saved session in the current screen: fetch its history and show it.
 *
 *  Shared by the sessions list and `/fork`, so the two cannot drift on what
 *  "open a session" means (which ids get reset, what happens on failure).
 *
 *  Opening is a read. It restores the agent and the route the conversation ran
 *  with into the composer, and must not write either back: a pick is the only
 *  thing that changes defaults, and a send is the only thing that changes a
 *  session's recorded route.
 */
import { getAgent, getSessionRoute, listMessages } from "../api/nova-api.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { recordsToMessages } from "../utils/history.ts";

/** Load *sessionId* into the transcript. Throws when the fetch fails. */
export async function openSession(
    sessionId: string,
    agentKey?: string | null,
): Promise<void> {
    const records = await listMessages(sessionId);
    useChatStore
        .getState()
        .loadHistory(sessionId, recordsToMessages(records));

    if (agentKey && agentKey !== useChatStore.getState().agentKey) {
        // The conversation belongs to an agent; continuing it under whichever
        // agent happens to be selected would change its prompt and tools.
        const agent = await getAgent(agentKey);
        useChatStore.setState({
            agentKey,
            agentName: agent?.name ?? agentKey,
        });
    }

    const route = await getSessionRoute(sessionId);
    if (route?.provider && route.model) {
        useChatStore.setState({
            provider: route.provider,
            model: route.model,
            reasoningEffort: route.reasoning_effort ?? "",
        });
    }
}
