/** Persisted session tabs, mirroring opencode: one file, one list per cwd.
 *
 *  Only tabs the user left open are stored; drafts (no session id) are not.
 *  The file is rewritten on every tab-list change, so an exit is always safe.
 */
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { useTabStore, type SessionTab } from "../stores/tab-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

type PersistedTab = { sessionId: string; title: string };
type CwdEntry = {
    tabs?: PersistedTab[];
    activeSessionId?: string | null;
};
type TabFile = { version?: number; cwd?: Record<string, CwdEntry> };

/** $NOVA_HOME/tui-tabs.json, resolved at call time so tests can redirect it. */
export function tabsPath(): string {
    return join(
        process.env.NOVA_HOME || join(homedir(), ".nova"),
        "tui-tabs.json",
    );
}

/** The workspace key used in the file. Absolute, so `nova` from a symlink and
 *  from its target do not become two sets. */
export function tabsCwdKey(): string {
    return resolve(WORKSPACE_DIR);
}

function readFile(): TabFile {
    try {
        const parsed = JSON.parse(readFileSync(tabsPath(), "utf-8")) as unknown;
        if (
            parsed !== null &&
            typeof parsed === "object" &&
            !Array.isArray(parsed)
        ) {
            return parsed as TabFile;
        }
    } catch {
        // Missing or malformed file: start with no tabs.
    }
    return { cwd: {} };
}

function sanitize(value: unknown): PersistedTab[] {
    if (!Array.isArray(value)) {
        return [];
    }
    const seen = new Set<string>();
    const tabs: PersistedTab[] = [];
    for (const item of value) {
        if (item === null || typeof item !== "object") {
            continue;
        }
        const record = item as { sessionId?: unknown; title?: unknown };
        const sessionId =
            typeof record.sessionId === "string"
                ? record.sessionId.trim()
                : "";
        if (!sessionId || seen.has(sessionId)) {
            continue;
        }
        seen.add(sessionId);
        tabs.push({
            sessionId,
            title:
                typeof record.title === "string" && record.title.trim()
                    ? record.title.trim()
                    : "Session",
        });
    }
    return tabs;
}

/** Restored tabs for one workspace, oldest first. */
export function loadTabs(cwd = tabsCwdKey()): PersistedTab[] {
    return sanitize(readFile().cwd?.[resolve(cwd)]?.tabs);
}

/** The session the workspace was last viewing, if it was persisted. */
export function loadActiveSessionId(cwd = tabsCwdKey()): string | null {
    const value = readFile().cwd?.[resolve(cwd)]?.activeSessionId;
    return typeof value === "string" && value ? value : null;
}

/** Replace one workspace's list, preserving every other workspace. */
export function saveTabs(
    cwd: string,
    tabs: readonly SessionTab[],
    activeSessionId: string | null = null,
): void {
    const key = resolve(cwd);
    const persisted = tabs
        .filter((tab) => tab.sessionId !== null)
        .map((tab) => ({
            sessionId: tab.sessionId!,
            title: tab.title,
        }));
    const payload = readFile();
    const cwdMap =
        payload.cwd !== null &&
        typeof payload.cwd === "object" &&
        !Array.isArray(payload.cwd)
            ? payload.cwd
            : {};
    cwdMap[key] = {
        tabs: sanitize(persisted),
        activeSessionId: activeSessionId || null,
    };
    const next: TabFile = { version: 1, ...payload, cwd: cwdMap };
    try {
        const file = tabsPath();
        mkdirSync(dirname(file), { recursive: true });
        const temporary = `${file}.${process.pid}.tmp`;
        writeFileSync(temporary, JSON.stringify(next));
        renameSync(temporary, file);
    } catch {
        // A failed write must not break the UI.
    }
}

/** Restored session ids, so a later prune only touches startup tabs. */
let restoredSessionIds = new Set<string>();
let restoredActiveId: string | null = null;

/** Fill the tab store from disk. Returns how many tabs were restored. */
export function hydrateTabs(cwd = tabsCwdKey()): number {
    const saved = loadTabs(cwd);
    restoredSessionIds = new Set(saved.map((tab) => tab.sessionId));
    restoredActiveId = loadActiveSessionId(cwd);
    useTabStore.getState().hydrate(saved);
    return saved.length;
}

/** The session the app was viewing last run, if it was persisted. */
export function restoredActiveSessionId(): string | null {
    return restoredActiveId;
}

/** Drop restored tabs whose session no longer exists. */
export function pruneRestoredTabs(validSessionIds: Set<string>): void {
    if (restoredSessionIds.size === 0) {
        return;
    }
    const state = useTabStore.getState();
    const dead = state.tabs.filter(
        (tab) =>
            tab.sessionId !== null &&
            restoredSessionIds.has(tab.sessionId) &&
            !validSessionIds.has(tab.sessionId),
    );
    if (dead.length > 0) {
        state.removeTabs(dead.map((tab) => tab.id));
        for (const tab of dead) {
            useChatStore.getState().remove(tab.id);
        }
    }
    restoredSessionIds.clear();
}

function signature(
    tabs: readonly SessionTab[],
    activeSessionId: string | null,
): string {
    const list = tabs
        .filter((tab) => tab.sessionId !== null)
        .map((tab) => `${tab.sessionId}\u0000${tab.title}`)
        .join("\u0001");
    return `${list}\u0002${activeSessionId ?? ""}`;
}

function activeSessionId(state: {
    tabs: readonly SessionTab[];
    activeId: string | null;
}): string | null {
    return (
        state.tabs.find((tab) => tab.id === state.activeId)?.sessionId ?? null
    );
}

let installed = false;

/** Persist on every change to the saved tab list; returns an uninstall. */
export function installTabPersistence(cwd = tabsCwdKey()): () => void {
    if (installed) {
        return () => {};
    }
    installed = true;
    const key = resolve(cwd);
    let current = signature(
        useTabStore.getState().tabs,
        activeSessionId(useTabStore.getState()),
    );
    const unsubscribe = useTabStore.subscribe((state) => {
        const active = activeSessionId(state);
        const next = signature(state.tabs, active);
        if (next === current) {
            return;
        }
        current = next;
        saveTabs(key, state.tabs, active);
    });
    return () => {
        installed = false;
        unsubscribe();
    };
}

/** Test hook: forget module state between suites. */
export function resetTabPersistenceForTest(): void {
    installed = false;
    restoredSessionIds = new Set();
    restoredActiveId = null;
}
