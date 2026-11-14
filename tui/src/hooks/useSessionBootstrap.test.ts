import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import {
    applyPendingAttention,
    restoreActiveTab,
    syncAgentsFromSessions,
} from "./useSessionBootstrap.ts";
import {
    hydrateTabs,
    resetTabPersistenceForTest,
} from "../lib/tab-persistence.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

type Session = {
    id: string;
    title: string | null;
    updated_at: number;
    agent_key: string;
};

function session(id: string, agentKey = ""): Session {
    return { id, title: null, updated_at: 0, agent_key: agentKey };
}

/** Restore one tab for *sessionId* and make it the session to come back to. */
function persistTab(sessionId: string): void {
    const home = mkdtempSync(join(tmpdir(), "nova-tabs-"));
    previousHome = process.env.NOVA_HOME;
    process.env.NOVA_HOME = home;
    writeFileSync(
        join(home, "tui-tabs.json"),
        JSON.stringify({
            version: 1,
            cwd: {
                [resolve(WORKSPACE_DIR)]: {
                    tabs: [{ sessionId, title: sessionId }],
                    activeSessionId: sessionId,
                },
            },
        }),
    );
    resetTabPersistenceForTest();
    hydrateTabs();
}

let previousHome: string | undefined;

beforeEach(() => {
    useTabStore.getState().reset();
    useChatStore.getState().reset();
});

afterEach(() => {
    useTabStore.getState().reset();
    useChatStore.getState().reset();
    resetTabPersistenceForTest();
    if (previousHome === undefined) {
        delete process.env.NOVA_HOME;
    } else {
        process.env.NOVA_HOME = previousHome;
    }
});

test("an agent is restored only for a startup tab with an agent key", () => {
    const tab = useTabStore.getState().create({ sessionId: "s1" });
    const startupTabIds = new Set([tab.id]);

    syncAgentsFromSessions([session("s1", "alpha")], startupTabIds);
    expect(useChatStore.getState().byId[tab.id]?.agentKey).toBe("alpha");

    // A tab opened after startup does not inherit the session's agent.
    const later = useTabStore.getState().create({ sessionId: "s2" });
    syncAgentsFromSessions(
        [session("s1", "alpha"), session("s2", "beta")],
        startupTabIds,
    );
    expect(useChatStore.getState().byId[later.id]?.agentKey).toBeUndefined();
});

test("a session without an agent key leaves the tab alone", () => {
    const tab = useTabStore.getState().create({ sessionId: "s1" });
    syncAgentsFromSessions([session("s1", "")], new Set([tab.id]));
    expect(useChatStore.getState().byId[tab.id]?.agentKey).toBeUndefined();
});

test("a pending prompt badges the tab that waits for the user", () => {
    const tab = useTabStore.getState().create({ sessionId: "s1" });

    applyPendingAttention({ s1: { approvals: 0, ask: true } });
    expect(
        useTabStore.getState().tabs.find((item) => item.id === tab.id)?.attention,
    ).toBe("question");

    applyPendingAttention({ s1: { approvals: 2, ask: false } });
    expect(
        useTabStore.getState().tabs.find((item) => item.id === tab.id)?.attention,
    ).toBe("approval");

    applyPendingAttention({ s1: { approvals: 0, ask: false } });
    expect(
        useTabStore.getState().tabs.find((item) => item.id === tab.id)?.attention,
    ).toBeNull();
});

test("the session from last run is restored when it still exists", () => {
    persistTab("s1");
    const tab = useTabStore.getState().tabs[0]!;
    expect(useTabStore.getState().activeId).toBeNull();

    restoreActiveTab([session("s1")]);
    expect(useTabStore.getState().activeId).toBe(tab.id);
});

test("a restored session that was pruned is not brought back", () => {
    persistTab("s1");

    restoreActiveTab([]);
    expect(useTabStore.getState().activeId).toBeNull();
});
