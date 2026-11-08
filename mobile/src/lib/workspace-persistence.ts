/** Tab persistence: restore the saved tab set, debounce writes per server. */
import { useConnection } from "../state/connection";
import { useTabs } from "../state/tabs";
import {
    emptyTabsFile,
    parseTabsFile,
    savedWorkspace,
    serverKey,
    withSavedTabs,
    type TabsFile,
} from "../tabs/persistence";
import { readTabsFile, writeTabsFile } from "./storage";

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

/** Load this server's saved tabs and hydrate the tab store. */
export async function loadWorkspaceTabs(): Promise<void> {
    const { baseUrl, username } = useConnection.getState();
    workspaceKey = serverKey(baseUrl, username);
    tabFile = parseTabsFile(await readTabsFile());
    const saved = savedWorkspace(tabFile, workspaceKey);
    useTabs.getState().hydrate(saved.tabs, saved.activeSessionId);
    lastSignature = signature();
}

/** Subscribe to tab changes for the current workspace. */
export function installPersistence(): void {
    unsubscribe?.();
    unsubscribe = useTabs.subscribe(() => scheduleSave());
}

/** Write the pending change immediately, e.g. when the app backgrounds. */
export function flushPersistence(): void {
    if (saveTimer !== null) {
        clearTimeout(saveTimer);
        saveTimer = null;
    }
    saveNow();
}

/** Forget the subscription, timer and cached file for the previous server. */
export function resetPersistence(): void {
    unsubscribe?.();
    unsubscribe = null;
    if (saveTimer !== null) {
        clearTimeout(saveTimer);
        saveTimer = null;
    }
    workspaceKey = "";
    lastSignature = "";
    tabFile = emptyTabsFile();
}
