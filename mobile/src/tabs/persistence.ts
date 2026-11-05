/** Persisted session tabs, keyed by the server they belong to.
 *
 *  The TUI keys tabs by working directory (`tui/src/lib/tab-persistence.ts`).
 *  The mobile client has no cwd; one phone may point at several Nova servers,
 *  so the key is the canonical server origin plus the signed-in user. Mixing
 *  them would show one server's sessions against another server's credentials.
 *
 *  Only tabs the user left open are stored. Drafts (no session id) are not,
 *  and a workspace with no tabs is stored as an empty list so closing every tab
 *  is remembered instead of resurrecting the previous set.
 *
 *  This module is pure: the app owns AsyncStorage and calls `parseTabsFile` /
 *  `withSavedTabs` around it.
 */
import type { SessionTab } from "./tab-state";

export type PersistedTab = { sessionId: string; title: string };

export type PersistedWorkspace = {
    tabs: PersistedTab[];
    activeSessionId: string | null;
};

export type TabsFile = {
    version: 1;
    servers: Record<string, PersistedWorkspace>;
};

export function emptyTabsFile(): TabsFile {
    return { version: 1, servers: {} };
}

function stripTrailingSlashes(value: string): string {
    return value.replace(/\/+$/, "");
}

/**
 * Canonical key for one server connection.
 *
 * The app should pass the URL it actually requests. A missing scheme is left
 * as-is rather than guessed, so `host:8765` and `https://host:8765` cannot
 * silently collapse into one workspace.
 */
export function serverKey(baseUrl: string, username = ""): string {
    const trimmed = baseUrl.trim();
    let normalized = stripTrailingSlashes(trimmed);
    try {
        const url = new URL(trimmed);
        url.hash = "";
        url.search = "";
        url.pathname = stripTrailingSlashes(url.pathname) || "/";
        normalized = stripTrailingSlashes(url.toString());
    } catch {
        // RN's URL polyfill rejects some inputs; the trimmed string is enough.
    }
    const user = username.trim().toLowerCase();
    return user ? `${normalized}|${user}` : normalized;
}

function sanitizeTabs(value: unknown): PersistedTab[] {
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

function sanitizeWorkspace(value: unknown): PersistedWorkspace {
    if (value === null || typeof value !== "object") {
        return { tabs: [], activeSessionId: null };
    }
    const record = value as { tabs?: unknown; activeSessionId?: unknown };
    return {
        tabs: sanitizeTabs(record.tabs),
        activeSessionId:
            typeof record.activeSessionId === "string" &&
            record.activeSessionId.trim()
                ? record.activeSessionId.trim()
                : null,
    };
}

/** Read stored JSON without trusting it; malformed input is an empty file. */
export function parseTabsFile(raw: unknown): TabsFile {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
        return emptyTabsFile();
    }
    const record = raw as { servers?: unknown };
    if (
        record.servers === null ||
        typeof record.servers !== "object" ||
        Array.isArray(record.servers)
    ) {
        return emptyTabsFile();
    }
    const servers: Record<string, PersistedWorkspace> = {};
    for (const [key, value] of Object.entries(record.servers)) {
        if (!key.trim()) {
            continue;
        }
        servers[key] = sanitizeWorkspace(value);
    }
    return { version: 1, servers };
}

/** Tabs saved for one connection; an empty workspace when none were saved. */
export function savedWorkspace(
    file: TabsFile,
    key: string,
): PersistedWorkspace {
    return file.servers[key] ?? { tabs: [], activeSessionId: null };
}

/**
 * Replace one connection's saved tabs, preserving every other connection.
 *
 * `tabs` is the live tab list; drafts are dropped here rather than at the call
 * site so no caller can persist a session id it does not have yet.
 */
export function withSavedTabs(
    file: TabsFile,
    key: string,
    tabs: readonly Pick<SessionTab, "sessionId" | "title">[],
    activeSessionId: string | null = null,
): TabsFile {
    const persisted = sanitizeTabs(
        tabs
            .filter((tab) => tab.sessionId !== null)
            .map((tab) => ({
                sessionId: tab.sessionId!,
                title: tab.title,
            })),
    );
    return {
        version: 1,
        servers: {
            ...file.servers,
            [key]: {
                tabs: persisted,
                activeSessionId: activeSessionId?.trim() || null,
            },
        },
    };
}

/** Serialize through JSON.stringify; kept here so callers use one shape. */
export function serializeTabsFile(file: TabsFile): string {
    return JSON.stringify(file);
}
