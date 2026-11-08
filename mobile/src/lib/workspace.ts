/**
 * Workspace lifecycle: restore tabs for one server, prune stale tabs, and
 * start the event tail. Persistence and the SSE tail live in their own modules.
 */
import { useAttachments } from "../state/attachments";
import { useCatalog } from "../state/catalog";
import { useChat } from "../state/chat";
import { useChatProgress } from "../state/chat-progress";
import { useDrafts } from "../state/drafts";
import { useProjects } from "../state/projects";
import { useRoute } from "../state/route";
import { useSessions } from "../state/sessions";
import { useTabs } from "../state/tabs";
import { useTasks } from "../state/tasks";
import { startSessionEvents, stopSessionEvents } from "./session-events";
import { ensureLoaded, resetLoadedTabs } from "./tab-actions";
import {
    flushPersistence,
    installPersistence,
    loadWorkspaceTabs,
    resetPersistence,
} from "./workspace-persistence";
import { dropTabStream, resetStreams } from "./stream-runner";

/** Restore the saved tab set for the connected server. */
export async function bootstrapWorkspace(): Promise<void> {
    resetWorkspace();
    await loadWorkspaceTabs();

    await Promise.all([
        useSessions.getState().refresh(),
        useCatalog.getState().refresh(),
        useProjects.getState().refresh(),
    ]);

    // A failed list is not proof that every saved session is gone; pruning on
    // an empty result would erase the user's tabs on a flaky connection.
    if (!useSessions.getState().error) {
        const valid = new Set(
            useSessions.getState().items.map((item) => item.id),
        );
        const state = useTabs.getState();
        const dead = state.tabs
            .filter(
                (tab) => tab.sessionId !== null && !valid.has(tab.sessionId),
            )
            .map((tab) => tab.id);
        if (dead.length > 0) {
            for (const tabId of dead) {
                dropTabStream(tabId);
                useChat.getState().remove(tabId);
                useChatProgress.getState().remove(tabId);
            }
            useTabs.getState().remove(dead);
        }
    }

    // Restored tabs start without a chat slice; remember which agent each
    // session belongs to so an existing-session send keeps addressing it.
    for (const item of useSessions.getState().items) {
        const tab = useTabs
            .getState()
            .tabs.find((candidate) => candidate.sessionId === item.id);
        if (tab) {
            useChat.getState().setAgent(tab.id, item.agent_key);
            useChat.getState().setProjectId(tab.id, item.project_id);
        }
    }

    installPersistence();
    startSessionEvents();

    const active = useTabs.getState().tabs.find(
        (tab) => tab.id === useTabs.getState().activeId,
    );
    if (active) {
        await ensureLoaded(active.id);
    }
}

/** Drop every in-memory workspace value; the next connect restores its own. */
export function resetWorkspace(): void {
    stopSessionEvents();
    resetPersistence();
    resetStreams();
    resetLoadedTabs();
    useTabs.getState().reset();
    useChat.getState().reset();
    useChatProgress.getState().reset();
    useCatalog.getState().reset();
    useDrafts.getState().reset();
    useAttachments.getState().reset();
    useRoute.getState().reset();
    useSessions.getState().reset();
    useProjects.getState().reset();
    useTasks.getState().reset();
}

/** Persist a pending tab change now, e.g. when the app backgrounds. */
export function flushWorkspace(): void {
    flushPersistence();
}
