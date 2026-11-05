import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
    hydrateTabs,
    installTabPersistence,
    loadActiveSessionId,
    loadTabs,
    pruneRestoredTabs,
    resetTabPersistenceForTest,
    restoredActiveSessionId,
    saveTabs,
    tabsPath,
} from "./tab-persistence.ts";
import { useTabStore, type SessionTab } from "../stores/tab-store.ts";

const originalHome = process.env.NOVA_HOME;
const CWD = "/workspace/smoke";

function tab(sessionId: string | null, title = "Session"): SessionTab {
    return {
        id: `tab_${sessionId ?? "draft"}`,
        sessionId,
        title,
        unread: null,
        attention: null,
    };
}

beforeEach(() => {
    process.env.NOVA_HOME = mkdtempSync(join(tmpdir(), "nova-tabs-"));
    useTabStore.getState().reset();
    resetTabPersistenceForTest();
});

afterEach(() => {
    resetTabPersistenceForTest();
    if (originalHome === undefined) {
        delete process.env.NOVA_HOME;
    } else {
        process.env.NOVA_HOME = originalHome;
    }
});

describe("tab persistence", () => {
    test("saves only real tabs", () => {
        saveTabs(CWD, [tab("s1", "First"), tab(null, "Draft")]);
        expect(loadTabs(CWD)).toEqual([{ sessionId: "s1", title: "First" }]);
    });

    test("preserves the other workspace lists", () => {
        saveTabs("/workspace/a", [tab("s1", "A")]);
        saveTabs("/workspace/b", [tab("s2", "B")]);
        expect(loadTabs("/workspace/a")).toEqual([
            { sessionId: "s1", title: "A" },
        ]);
        expect(loadTabs("/workspace/b")).toEqual([
            { sessionId: "s2", title: "B" },
        ]);
    });

    test("restores, dedupes and skips empty ids", () => {
        writeFileSync(
            tabsPath(),
            JSON.stringify({
                cwd: {
                    [CWD]: {
                        tabs: [
                            { sessionId: "s1", title: "First" },
                            { sessionId: "s1", title: "Duplicate" },
                            { sessionId: "", title: "Draft" },
                            { sessionId: "s2" },
                        ],
                    },
                },
            }),
        );
        expect(hydrateTabs(CWD)).toBe(2);
        const tabs = useTabStore.getState().tabs;
        expect(tabs.map((item) => item.sessionId)).toEqual(["s1", "s2"]);
        expect(tabs[0]?.title).toBe("First");
        expect(tabs[1]?.title).toBe("Session");
        expect(useTabStore.getState().activeId).toBeNull();
    });

    test("a malformed file is treated as empty", () => {
        writeFileSync(tabsPath(), "{not json");
        expect(loadTabs(CWD)).toEqual([]);
    });

    test("pruning drops only missing restored tabs", () => {
        saveTabs(CWD, [tab("keep", "Keep"), tab("gone", "Gone")]);
        hydrateTabs(CWD);
        const extra = useTabStore.getState().create({ sessionId: "fresh" });

        pruneRestoredTabs(new Set(["keep"]));
        expect(
            useTabStore.getState().tabs.map((item) => item.sessionId),
        ).toEqual(["keep", "fresh"]);
        expect(
            useTabStore.getState().tabs.some((item) => item.id === extra.id),
        ).toBe(true);
    });

    test("installation writes on list changes but not on unread or drafts", () => {
        const uninstall = installTabPersistence(CWD);
        try {
            const draft = useTabStore.getState().create();
            expect(loadTabs(CWD)).toEqual([]);

            useTabStore.getState().adopt(draft.id, "s1");
            expect(loadTabs(CWD)).toEqual([
                { sessionId: "s1", title: "New session" },
            ]);

            useTabStore.getState().markTurnEnded(draft.id, true);
            expect(loadTabs(CWD)).toEqual([
                { sessionId: "s1", title: "New session" },
            ]);

            useTabStore.getState().renameTab(draft.id, "Renamed");
            expect(loadTabs(CWD)).toEqual([
                { sessionId: "s1", title: "Renamed" },
            ]);

            useTabStore.getState().close(draft.id);
            expect(loadTabs(CWD)).toEqual([]);
        } finally {
            uninstall();
        }
    });

    test("the stored file is valid JSON and keeps a version", () => {
        saveTabs(CWD, [tab("s1", "First")]);
        const payload = JSON.parse(readFileSync(tabsPath(), "utf-8")) as {
            version?: number;
        };
        expect(payload.version).toBe(1);
    });

    test("the active session is saved and restored", () => {
        saveTabs(CWD, [tab("s1", "First"), tab("s2", "Second")], "s2");
        expect(loadTabs(CWD).map((item) => item.sessionId)).toEqual([
            "s1",
            "s2",
        ]);
        expect(loadActiveSessionId(CWD)).toBe("s2");

        useTabStore.getState().reset();
        hydrateTabs(CWD);
        expect(restoredActiveSessionId()).toBe("s2");
        expect(useTabStore.getState().tabs.map((item) => item.sessionId)).toEqual(
            ["s1", "s2"],
        );
    });

    test("selecting a tab persists the active session", () => {
        const uninstall = installTabPersistence(CWD);
        try {
            const first = useTabStore
                .getState()
                .create({ sessionId: "s1", title: "First" });
            const second = useTabStore
                .getState()
                .create({ sessionId: "s2", title: "Second" });
            useTabStore.getState().select(second.id);

            expect(loadActiveSessionId(CWD)).toBe("s2");
            useTabStore.getState().select(first.id);
            expect(loadActiveSessionId(CWD)).toBe("s1");
        } finally {
            uninstall();
        }
    });
});
