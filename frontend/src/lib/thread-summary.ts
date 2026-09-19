import i18n from "../i18n";
import { DEFAULT_AGENT_KEY } from "./nova-constants";
import type { NovaSessionSummary, NovaThreadSummary } from "../types/nova";

/**
 * Resolve a session's display title, falling back to a localized "untitled"
 * label when the title is missing or blank.
 */
export function toThreadTitle(session: NovaSessionSummary): string {
    const untitled = i18n.t("app.untitledSession");
    return (session.title || untitled).trim() || untitled;
}

/**
 * Project a backend session summary into the frontend thread summary shape,
 * normalizing nullable fields and defaulting the agent key.
 */
export function toThreadSummary(session: NovaSessionSummary): NovaThreadSummary {
    return {
        id: session.id,
        title: toThreadTitle(session),
        status: "regular",
        workspace_dir: session.workspace_dir ?? null,
        pinned: session.pinned ?? false,
        updated_at: session.updated_at,
        project_id: session.project_id ?? null,
        agent_key: session.agent_key || DEFAULT_AGENT_KEY,
    };
}

/**
 * Insert or replace a thread at the head of the list, preserving order for the
 * remaining threads.
 */
export function upsertThread(
    threads: NovaThreadSummary[],
    nextThread: NovaThreadSummary,
): NovaThreadSummary[] {
    const filtered = threads.filter((thread) => thread.id !== nextThread.id);
    return [nextThread, ...filtered];
}
