import { afterEach, beforeEach, expect, test } from "bun:test";

import {
    applyPendingAttention,
    syncAgentsFromSessions,
} from "./useSessionBootstrap.ts";
import { resetTabPersistenceForTest } from "../lib/tab-persistence.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useTabStore } from "../stores/tab-store.ts";

type Session = {
    id: string;
    title: string | null;
    updated_at: number;
    agent_key: string;
};

function session(id: string, agentKey = ""): Session {
    return { id, title: null, updated_at: 0, agent_key: agentKey };
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

