import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { selectIsLaunching, useChatStore } from "../stores/chat-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { ensureStartupDraft, selectTab } from "./tab-actions.ts";

beforeEach(() => {
    useTabStore.getState().reset();
    useChatStore.getState().reset();
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        retry: null,
        byId: {},
    });
});

afterEach(() => {
    useTabStore.getState().reset();
    useChatStore.getState().reset();
});

describe("draft tabs", () => {
    test("switching away from an untouched draft drops it", () => {
        const draft = useTabStore.getState().create();
        const saved = useTabStore.getState().create({ sessionId: "s1" });
        selectTab(draft.id);

        selectTab(saved.id);

        expect(useTabStore.getState().tabs.map((tab) => tab.id)).toEqual([
            saved.id,
        ]);
        expect(useTabStore.getState().activeId).toBe(saved.id);
    });

    test("a draft that already holds a message is a live turn, not a placeholder", () => {
        const draft = useTabStore.getState().create();
        const saved = useTabStore.getState().create({ sessionId: "s1" });
        selectTab(draft.id);
        useChatStore.getState().addUserMessage("hello", undefined, draft.id);

        selectTab(saved.id);

        expect(useTabStore.getState().tabs.map((tab) => tab.id)).toContain(
            draft.id,
        );
        expect(useChatStore.getState().byId[draft.id]?.messages).toHaveLength(1);
    });

    test("a draft that learned its session id is a real tab", () => {
        const draft = useTabStore.getState().create();
        const other = useTabStore.getState().create({ sessionId: "s2" });
        selectTab(draft.id);
        useTabStore.getState().adopt(draft.id, "s1");

        selectTab(other.id);

        expect(useTabStore.getState().tabs.map((tab) => tab.id)).toContain(
            draft.id,
        );
    });

    test("startup lands on one draft, however often it is asked", () => {
        ensureStartupDraft();
        ensureStartupDraft();

        const tabs = useTabStore.getState().tabs;
        expect(tabs).toHaveLength(1);
        expect(tabs[0]?.sessionId).toBeNull();
        expect(useTabStore.getState().activeId).toBe(tabs[0]!.id);
    });
});

describe("switching tabs", () => {
    test("a session tab is never mistaken for the launch screen before history arrives", () => {
        const draft = useTabStore.getState().create();
        const saved = useTabStore.getState().create({ sessionId: "s1" });
        selectTab(draft.id);

        selectTab(saved.id);

        const state = useChatStore.getState();
        expect(state.sessionId).toBe("s1");
        expect(state.messages).toEqual([]);
        expect(selectIsLaunching(state)).toBe(false);
    });

    test("a draft still lands on the launch screen", () => {
        const saved = useTabStore.getState().create({ sessionId: "s1" });
        const draft = useTabStore.getState().create();
        selectTab(saved.id);

        selectTab(draft.id);

        expect(useChatStore.getState().sessionId).toBeNull();
        expect(selectIsLaunching(useChatStore.getState())).toBe(true);
    });
});
