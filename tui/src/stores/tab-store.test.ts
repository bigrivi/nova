import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
    NEW_TAB_TITLE,
    tabSequence,
    setTabSequence,
    useTabStore,
} from "./tab-store.ts";

beforeEach(() => {
    useTabStore.getState().reset();
});

afterEach(() => {
    useTabStore.getState().reset();
});

describe("tab store", () => {
    test("creates a draft with a stable id", () => {
        const tab = useTabStore.getState().create();
        expect(tab.id).toStartWith("tab_");
        expect(tab.sessionId).toBeNull();
        expect(tab.title).toBe(NEW_TAB_TITLE);
        expect(useTabStore.getState().tabs).toEqual([tab]);
    });

    test("adopting a session keeps the tab identity", () => {
        const tab = useTabStore.getState().create();
        useTabStore.getState().adopt(tab.id, "s1");
        const stored = useTabStore.getState().tabs[0]!;
        expect(stored.id).toBe(tab.id);
        expect(stored.sessionId).toBe("s1");
    });

    test("select clears the unread marker", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useTabStore.getState().select(first.id);
        useTabStore.getState().markTurnEnded(second.id, true);
        expect(
            useTabStore.getState().tabs.find((tab) => tab.id === second.id)
                ?.unread,
        ).toBe("activity");

        useTabStore.getState().select(second.id);
        expect(
            useTabStore.getState().tabs.find((tab) => tab.id === second.id)
                ?.unread,
        ).toBeNull();
    });

    test("a turn ending in the focused active tab is not unread", () => {
        const tab = useTabStore.getState().create();
        useTabStore.getState().select(tab.id);
        useTabStore.getState().markTurnEnded(tab.id, true);
        expect(useTabStore.getState().tabs[0]!.unread).toBeNull();
    });

    test("a blurred active tab keeps the completion unread", () => {
        const tab = useTabStore.getState().create();
        useTabStore.getState().select(tab.id);
        useTabStore.getState().setFocused(false);
        useTabStore.getState().markTurnEnded(tab.id, true);
        expect(useTabStore.getState().tabs[0]!.unread).toBe("activity");

        useTabStore.getState().setFocused(true);
        expect(useTabStore.getState().tabs[0]!.unread).toBeNull();
    });

    test("a failed turn is marked as error", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useTabStore.getState().select(first.id);
        useTabStore.getState().markTurnEnded(second.id, false);
        expect(
            useTabStore.getState().tabs.find((tab) => tab.id === second.id)
                ?.unread,
        ).toBe("error");
    });

    test("attention can be set and cleared", () => {
        const tab = useTabStore.getState().create();
        useTabStore.getState().setAttention(tab.id, "approval");
        expect(useTabStore.getState().tabs[0]!.attention).toBe("approval");
        useTabStore.getState().setAttention(tab.id, null);
        expect(useTabStore.getState().tabs[0]!.attention).toBeNull();
    });

    test("closing selects the right neighbour, then the left", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        const third = useTabStore.getState().create();
        useTabStore.getState().select(second.id);

        expect(useTabStore.getState().close(second.id)).toBe(third.id);
        expect(useTabStore.getState().close(third.id)).toBe(first.id);
        expect(useTabStore.getState().close(first.id)).toBeNull();
    });

    test("closing a background tab leaves the active tab alone", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useTabStore.getState().select(first.id);
        expect(useTabStore.getState().close(second.id)).toBe(first.id);
        expect(useTabStore.getState().activeId).toBe(first.id);
    });

    test("reopen restores the tab at its original position", () => {
        const first = useTabStore.getState().create({ title: "first" });
        const middle = useTabStore.getState().create({ title: "middle" });
        useTabStore.getState().create({ title: "last" });
        useTabStore.getState().select(first.id);
        useTabStore.getState().close(middle.id);

        const reopened = useTabStore.getState().reopen();
        expect(reopened?.id).toBe(middle.id);
        expect(useTabStore.getState().tabs.map((tab) => tab.title)).toEqual([
            "first",
            "middle",
            "last",
        ]);
    });

    test("titles update by session id", () => {
        const tab = useTabStore.getState().create({ sessionId: "s1" });
        useTabStore.getState().setTitle("s1", "Renamed");
        expect(
            useTabStore.getState().tabs.find((item) => item.id === tab.id)
                ?.title,
        ).toBe("Renamed");
    });

    test("the resume cursor survives tab updates but not a reset", () => {
        const tab = useTabStore.getState().create();
        setTabSequence(tab.id, 42);
        expect(tabSequence(tab.id)).toBe(42);
        useTabStore.getState().reset();
        expect(tabSequence(tab.id)).toBe(0);
    });

    test("hydrate fills an empty store and dedupes", () => {
        useTabStore.getState().hydrate([
            { sessionId: "s1", title: "First" },
            { sessionId: "s1", title: "Duplicate" },
            { sessionId: "", title: "Draft" },
        ]);
        expect(useTabStore.getState().tabs.map((tab) => tab.sessionId)).toEqual([
            "s1",
        ]);
        expect(useTabStore.getState().tabs[0]?.title).toBe("First");
        expect(useTabStore.getState().activeId).toBeNull();
    });

    test("hydrate never clobbers an existing tab", () => {
        const existing = useTabStore.getState().create();
        useTabStore.getState().hydrate([{ sessionId: "s1", title: "First" }]);
        expect(useTabStore.getState().tabs.map((tab) => tab.id)).toEqual([
            existing.id,
        ]);
    });

    test("removeTabs drops the ids and clears a removed active tab", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useTabStore.getState().select(first.id);
        useTabStore.getState().removeTabs([first.id]);
        expect(useTabStore.getState().tabs.map((tab) => tab.id)).toEqual([
            second.id,
        ]);
        expect(useTabStore.getState().activeId).toBeNull();
    });
});
