import type { NovaAgent } from "../types/nova";

/**
 * Display name for the agent that owns a chat.
 *
 * The name is the agents-table `name` (the same source the composer's context
 * bar and the agent picker use), so the assistant message header stays
 * consistent with the agent the session is actually bound to. Falls back to the
 * raw key when the agent is missing (e.g. it was deleted) or unnamed, and to the
 * supplied default when no key is known yet.
 */
export function agentDisplayName(
    agents: readonly NovaAgent[],
    agentKey: string | null | undefined,
    fallback = "Nova",
): string {
    if (!agentKey) {
        return fallback;
    }
    const agent = agents.find((item) => item.key === agentKey);
    return agent?.name || agentKey || fallback;
}
