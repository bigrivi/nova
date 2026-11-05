import { describe, expect, test } from "bun:test";

import { TabSequences } from "./sequences";
import {
    emptyTabsFile,
    parseTabsFile,
    savedWorkspace,
    serializeTabsFile,
    serverKey,
    withSavedTabs,
} from "./persistence";
import {
    NEW_TAB_TITLE,
    activeTab,
    adoptSession,
    clearUnread,
    closeTab,
    createTab,
    cycleTab,
    hydrateTabs,
    initialTabsState,
    makeTabId,
    markTurnEnded,
    pruneToSessions,
    removeTabs,
    renameTab,
    reopenTab,
    selectTab,
    setAttention,
    setFocused,
    setTitleBySession,
    tabForSession,
    type TabsState,
} from "./tab-state";

const NOW = 1_700_000_000_000;

function threeTabs(): {
    state: TabsState;
    first: string;
    second: string;
    third: string;
} {
    let state = initialTabsState();
    const first = createTab(state, { now: NOW });
    state = first.state;
    const second = createTab(state, { now: NOW });
    state = second.state;
    const third = createTab(state, { now: NOW });
    return {
        state: third.state,
        first: first.tab.id,
        second: second.tab.id,
        third: third.tab.id,
    };
}

describe("tab state", () => {
    test("creates a draft with a stable id", () => {
        const { state, tab } = createTab(initialTabsState(), { now: NOW });
        expect(tab.id.startsWith("tab_")).toBe(true);
        expect(tab.sessionId).toBeNull();
        expect(tab.title).toBe(NEW_TAB_TITLE);
        expect(state.tabs).toEqual([tab]);
        expect(state.activeId).toBeNull();
    });

    test("ids stay unique when created in the same millisecond", () => {
        const first = makeTabId();
        const second = makeTabId();
        expect(first).not.toBe(second);
    });

    test("adopting a session keeps the tab identity", () => {
        const { state, tab } = createTab(initialTabsState(), { now: NOW });
        const adopted = adoptSession(state, tab.id, "s1");
        expect(adopted.tabs[0]!.id).toBe(tab.id);
        expect(adopted.tabs[0]!.sessionId).toBe("s1");
    });

    test("select clears the unread marker and stamps the view time", () => {
        const { state, first, second } = threeTabs();
        const selected = selectTab(state, first, NOW);
        const ended = markTurnEnded(setFocused(selected, false), second, true);
        expect(ended.tabs.find((tab) => tab.id === second)?.unread).toBe(
            "activity",
        );

        const viewed = selectTab(ended, second, NOW + 10);
        expect(viewed.tabs.find((tab) => tab.id === second)?.unread).toBeNull();
        expect(viewed.tabs.find((tab) => tab.id === second)?.lastViewedAt).toBe(
            NOW + 10,
        );
    });

    test("a turn ending in the focused active tab is not unread", () => {
        const { state, first } = threeTabs();
        const selected = selectTab(state, first, NOW);
        const ended = markTurnEnded(selected, first, true);
        expect(ended.tabs[0]!.unread).toBeNull();
    });

    test("a blurred active tab keeps the completion unread", () => {
        const { state, first } = threeTabs();
        const selected = setFocused(selectTab(state, first, NOW), false);
        const ended = markTurnEnded(selected, first, true);
        expect(ended.tabs[0]!.unread).toBe("activity");

        const resumed = setFocused(ended, true);
        expect(resumed.tabs[0]!.unread).toBeNull();
    });

    test("a failed turn is marked as error", () => {
        const { state, first, second } = threeTabs();
        const selected = selectTab(state, first, NOW);
        const ended = markTurnEnded(selected, second, false);
        expect(ended.tabs.find((tab) => tab.id === second)?.unread).toBe(
            "error",
        );
    });

    test("setFocused is a no-op when the value is unchanged", () => {
        const state = initialTabsState();
        expect(setFocused(state, true)).toBe(state);
    });

    test("attention can be set and cleared", () => {
        const { state, first } = threeTabs();
        const flagged = setAttention(state, first, "approval");
        expect(flagged.tabs[0]!.attention).toBe("approval");
        expect(setAttention(flagged, first, null).tabs[0]!.attention).toBeNull();
    });

    test("closing selects the right neighbour, then the left, then null", () => {
        const { state, first, second, third } = threeTabs();
        const active = selectTab(state, second, NOW);
        const closedSecond = closeTab(active, second);
        expect(closedSecond.nextId).toBe(third);
        const closedThird = closeTab(closedSecond.state, third);
        expect(closedThird.nextId).toBe(first);
        expect(closeTab(closedThird.state, first).nextId).toBeNull();
    });

    test("closing a background tab leaves the active tab alone", () => {
        const { state, first, second } = threeTabs();
        const active = selectTab(state, first, NOW);
        const result = closeTab(active, second);
        expect(result.nextId).toBe(first);
        expect(result.state.activeId).toBe(first);
    });

    test("reopen restores the tab at its original position", () => {
        let state = initialTabsState();
        const first = createTab(state, { title: "first", now: NOW });
        state = first.state;
        const middle = createTab(state, { title: "middle", now: NOW });
        state = middle.state;
        const last = createTab(state, { title: "last", now: NOW });
        state = selectTab(last.state, first.tab.id, NOW);
        state = closeTab(state, middle.tab.id).state;

        const reopened = reopenTab(state, NOW + 5);
        expect(reopened.tab?.id).toBe(middle.tab.id);
        expect(reopened.state.tabs.map((tab) => tab.title)).toEqual([
            "first",
            "middle",
            "last",
        ]);
        expect(reopened.state.activeId).toBe(middle.tab.id);
    });

    test("titles update by session id and by tab id", () => {
        let state = initialTabsState();
        const created = createTab(state, { sessionId: "s1", now: NOW });
        state = created.state;
        state = setTitleBySession(state, "s1", "Renamed");
        expect(state.tabs[0]!.title).toBe("Renamed");
        state = renameTab(state, created.tab.id, "Local");
        expect(state.tabs[0]!.title).toBe("Local");
    });

    test("hydrate fills an empty store, dedupes, and restores the active tab", () => {
        const state = hydrateTabs(
            initialTabsState(),
            [
                { sessionId: "s1", title: "First" },
                { sessionId: "s1", title: "Duplicate" },
                { sessionId: "s2", title: "Second" },
            ],
            "s2",
        );
        expect(state.tabs.map((tab) => tab.sessionId)).toEqual(["s1", "s2"]);
        expect(state.tabs[0]!.title).toBe("First");
        expect(activeTab(state)?.sessionId).toBe("s2");
    });

    test("hydrate ignores an active session that is not restored", () => {
        const state = hydrateTabs(
            initialTabsState(),
            [{ sessionId: "s1" }],
            "gone",
        );
        expect(state.activeId).toBeNull();
    });

    test("hydrate never clobbers an existing tab", () => {
        const existing = createTab(initialTabsState(), { now: NOW });
        const state = hydrateTabs(existing.state, [
            { sessionId: "s1", title: "First" },
        ]);
        expect(state.tabs.map((tab) => tab.id)).toEqual([existing.tab.id]);
    });

    test("prune drops dead sessions but keeps drafts", () => {
        let state = initialTabsState();
        const first = createTab(state, { sessionId: "s1", now: NOW });
        state = first.state;
        const second = createTab(state, { sessionId: "s2", now: NOW });
        state = second.state;
        const draft = createTab(state, { now: NOW });
        state = draft.state;

        const pruned = pruneToSessions(state, new Set(["s2"]));
        expect(pruned.tabs.map((tab) => tab.sessionId)).toEqual(["s2", null]);
    });

    test("removeTabs clears a removed active tab", () => {
        const { state, first, second, third } = threeTabs();
        const active = selectTab(state, first, NOW);
        const removed = removeTabs(active, [first]);
        expect(removed.tabs.map((tab) => tab.id)).toEqual([second, third]);
        expect(removed.activeId).toBeNull();
    });

    test("cycle wraps in both directions", () => {
        const { state, first, second, third } = threeTabs();
        const active = selectTab(state, first, NOW);
        expect(activeTab(cycleTab(active, 1))?.id).toBe(second);
        expect(activeTab(cycleTab(active, -1))?.id).toBe(third);
    });

    test("unknown ids are a no-op", () => {
        const { state } = threeTabs();
        expect(selectTab(state, "missing")).toBe(state);
        expect(activeTab(selectTab(state, "missing"))).toBeNull();
    });

    test("tabForSession finds the owning tab", () => {
        const created = createTab(initialTabsState(), {
            sessionId: "s1",
            now: NOW,
        });
        expect(tabForSession(created.state, "s1")?.id).toBe(created.tab.id);
        expect(tabForSession(created.state, "s2")).toBeNull();
    });

    test("clearUnread only touches its own tab", () => {
        const { state, first, second } = threeTabs();
        const marked = markTurnEnded(
            markTurnEnded(state, first, true),
            second,
            true,
        );
        const cleared = clearUnread(marked, first);
        expect(cleared.tabs[0]!.unread).toBeNull();
        expect(cleared.tabs[1]!.unread).toBe("activity");
    });
});

describe("tab sequences", () => {
    test("round-trips and clears cursors", () => {
        const sequences = new TabSequences();
        expect(sequences.get("tab_1")).toBe(0);
        sequences.set("tab_1", 42);
        expect(sequences.get("tab_1")).toBe(42);
        sequences.drop("tab_1");
        expect(sequences.get("tab_1")).toBe(0);

        sequences.set("tab_2", 7);
        sequences.clear();
        expect(sequences.get("tab_2")).toBe(0);
    });

    test("ignores frames from a tab that is no longer open", () => {
        const sequences = new TabSequences();
        sequences.set("tab_closed", 99, new Set(["tab_open"]));
        expect(sequences.get("tab_closed")).toBe(0);
    });
});

describe("tab persistence", () => {
    test("server keys normalize origin and user", () => {
        expect(serverKey("https://Example.COM:443/nova/", "Alice")).toBe(
            "https://example.com/nova|alice",
        );
        expect(serverKey("https://example.com/nova", "alice")).toBe(
            "https://example.com/nova|alice",
        );
        expect(serverKey("http://example.com:8765/")).toBe(
            "http://example.com:8765",
        );
    });

    test("different schemes and users stay separate", () => {
        expect(serverKey("http://host:8765", "a")).not.toBe(
            serverKey("https://host:8765", "a"),
        );
        expect(serverKey("https://host", "a")).not.toBe(
            serverKey("https://host", "b"),
        );
    });

    test("malformed input parses to an empty file", () => {
        expect(parseTabsFile(null)).toEqual(emptyTabsFile());
        expect(parseTabsFile([])).toEqual(emptyTabsFile());
        expect(parseTabsFile({ servers: [] })).toEqual(emptyTabsFile());
        expect(parseTabsFile({ servers: { "": { tabs: [] } } })).toEqual(
            emptyTabsFile(),
        );
    });

    test("round-trips tabs, drops drafts, and dedupes", () => {
        const key = serverKey("https://host", "u");
        const withTabs = withSavedTabs(
            emptyTabsFile(),
            key,
            [
                { sessionId: "s1", title: "One" },
                { sessionId: "s1", title: "Duplicate" },
                { sessionId: null, title: "Draft" },
                { sessionId: "s2", title: "  " },
            ],
            "s2",
        );
        const parsed = parseTabsFile(
            JSON.parse(serializeTabsFile(withTabs)),
        );
        expect(savedWorkspace(parsed, key)).toEqual({
            tabs: [
                { sessionId: "s1", title: "One" },
                { sessionId: "s2", title: "Session" },
            ],
            activeSessionId: "s2",
        });
    });

    test("writing one server preserves the others", () => {
        const a = serverKey("https://a");
        const b = serverKey("https://b");
        const first = withSavedTabs(emptyTabsFile(), a, [
            { sessionId: "s1", title: "A" },
        ]);
        const second = withSavedTabs(
            first,
            b,
            [{ sessionId: "s2", title: "B" }],
            "s2",
        );
        expect(savedWorkspace(second, a).tabs).toHaveLength(1);
        expect(savedWorkspace(second, b).activeSessionId).toBe("s2");
    });

    test("closing every tab is remembered as an empty workspace", () => {
        const key = serverKey("https://host");
        const file = withSavedTabs(emptyTabsFile(), key, [], null);
        expect(savedWorkspace(parseTabsFile(file), key)).toEqual({
            tabs: [],
            activeSessionId: null,
        });
    });
});
