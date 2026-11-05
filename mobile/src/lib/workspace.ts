/**
 * Workspace lifecycle: restore tabs for one server, persist them, and tail
 * server-initiated turns through `/api/events`.
 */
import { openSessionEvents } from "../api/events";
import type { SessionEventFrame } from "../api/types";
import { useAttachments } from "../state/attachments";
import { useChat } from "../state/chat";
import { useDrafts } from "../state/drafts";
import { useProjects } from "../state/projects";
import { useTasks } from "../state/tasks";
import { useRoute } from "../state/route";
import { useConnection } from "../state/connection";
import { useSessions } from "../state/sessions";
import { tabForSession, useTabs } from "../state/tabs";
import {
    emptyTabsFile,
    parseTabsFile,
    savedWorkspace,
    serverKey,
    withSavedTabs,
    type TabsFile,
} from "../tabs/persistence";
import { ensureLoaded, resetLoadedTabs } from "./tab-actions";
import { dropTabStream, resetStreams, resumeTurn } from "./stream-runner";
import { readTabsFile, writeTabsFile } from "./storage";

let eventsClose: (() => void) | null = null;
let unsubscribe: (() => void) | null = null;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let tabFile: TabsFile = emptyTabsFile();
let workspaceKey = "";
let lastSignature = "";

function signature(): string {
    const state = useTabs.getState();
    const active = state.tabs.find((tab) => tab.id === state.activeId);
    const tabs = state.tabs
        .filter((tab) => tab.sessionId !== null)
        .map((tab) => `${tab.sessionId}\u0000${tab.title}`)
        .join("\u0001");
    return `${tabs}\u0002${active?.sessionId ?? ""}`;
}

function saveNow(): void {
    if (!workspaceKey) {
        return;
    }
    const state = useTabs.getState();
    const active = state.tabs.find((tab) => tab.id === state.activeId);
    tabFile = withSavedTabs(
        tabFile,
        workspaceKey,
        state.tabs,
        active?.sessionId ?? null,
    );
    void writeTabsFile(tabFile);
}

function scheduleSave(): void {
    if (!workspaceKey) {
        return;
    }
    const next = signature();
    if (next === lastSignature) {
        return;
    }
    lastSignature = next;
    if (saveTimer !== null) {
        clearTimeout(saveTimer);
    }
    saveTimer = setTimeout(() => {
        saveTimer = null;
        saveNow();
    }, 300);
}

function installPersistence(): void {
    unsubscribe?.();
    unsubscribe = useTabs.subscribe(() => scheduleSave());
}

function tailActiveSessions(sessionIds: readonly string[]): void {
    for (const sessionId of sessionIds) {
        const tab = tabForSession(sessionId);
        if (!tab) {
            continue;
        }
        void resumeTurn(tab.id).catch(() => {
            // A tail that cannot start is retried by the next event/snapshot.
        });
    }
}

function handleFrame(frame: SessionEventFrame): void {
    switch (frame.type) {
        case "snapshot":
            useTasks.getState().replace(frame.tasks);
            tailActiveSessions(frame.active);
            return;
        case "state":
            if (frame.state === "active") {
                tailActiveSessions([frame.session_id]);
            }
            return;
        case "title":
            useTabs.getState().setTitle(frame.session_id, frame.title);
            useSessions.getState().updateTitle(frame.session_id, frame.title);
            return;
        case "task":
            useTasks.getState().update(frame.task);
            return;
        default:
            return;
    }
}

export function startSessionEvents(): void {
    eventsClose?.();
    eventsClose = openSessionEvents(handleFrame);
}

export function stopSessionEvents(): void {
    eventsClose?.();
    eventsClose = null;
}

/** Restore the saved tab set for the connected server. */
export async function bootstrapWorkspace(): Promise<void> {
    resetWorkspace();
    const { baseUrl, username } = useConnection.getState();
    workspaceKey = serverKey(baseUrl, username);
    tabFile = parseTabsFile(await readTabsFile());
    const saved = savedWorkspace(tabFile, workspaceKey);
    useTabs.getState().hydrate(saved.tabs, saved.activeSessionId);
    lastSignature = signature();

    await Promise.all([
        useSessions.getState().refresh(),
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
    unsubscribe?.();
    unsubscribe = null;
    if (saveTimer !== null) {
        clearTimeout(saveTimer);
        saveTimer = null;
    }
    resetStreams();
    resetLoadedTabs();
    useTabs.getState().reset();
    useChat.getState().reset();
    useDrafts.getState().reset();
    useAttachments.getState().reset();
    useRoute.getState().reset();
    useSessions.getState().reset();
    useProjects.getState().reset();
    useTasks.getState().reset();
    workspaceKey = "";
    lastSignature = "";
    tabFile = emptyTabsFile();
}

export function flushWorkspace(): void {
    if (saveTimer !== null) {
        clearTimeout(saveTimer);
        saveTimer = null;
    }
    saveNow();
}
