import { DEFAULT_AGENT_KEY, SELECTED_AGENT_KEY_STORAGE } from "./nova-constants";

/**
 * Read the persisted main-agent key, falling back to the default when storage
 * is unavailable (private mode, SSR) or empty.
 */
export function readStoredAgentKey(): string {
    try {
        if (typeof localStorage === "undefined") {
            return DEFAULT_AGENT_KEY;
        }
        return localStorage.getItem(SELECTED_AGENT_KEY_STORAGE) || DEFAULT_AGENT_KEY;
    } catch {
        return DEFAULT_AGENT_KEY;
    }
}

/**
 * Persist the selected main-agent key. Failures are swallowed so selection
 * still works for the current session when storage is unavailable.
 */
export function writeStoredAgentKey(agentKey: string): void {
    try {
        if (typeof localStorage === "undefined") {
            return;
        }
        localStorage.setItem(SELECTED_AGENT_KEY_STORAGE, agentKey);
    } catch {
        // Storage may be unavailable; selection still works for the session.
    }
}
