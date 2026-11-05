import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { chatSlice, useChatStore, type TuiMessage } from "./chat-store.ts";
import { useTabStore } from "./tab-store.ts";

function textOf(message: TuiMessage | undefined): string {
    return (
        message?.parts
            .filter((part) => part.type === "text")
            .map((part) => (part.type === "text" ? part.text : ""))
            .join("") ?? ""
    );
}

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
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        retry: null,
        byId: {},
    });
});

describe("per-tab chat slices", () => {
    test("a background stream keeps writing without touching the visible tab", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useChatStore.getState().activate(first.id, null);
        useTabStore.getState().select(first.id);

        const firstAssistant = useChatStore
            .getState()
            .startAssistantMessage(first.id);
        useChatStore
            .getState()
            .appendTextDelta(firstAssistant, "first", first.id);

        useChatStore.getState().activate(second.id, first.id);
        useTabStore.getState().select(second.id);
        const secondAssistant = useChatStore
            .getState()
            .startAssistantMessage(second.id);
        useChatStore
            .getState()
            .appendTextDelta(secondAssistant, "second", second.id);

        // The first tab keeps streaming while the second is on screen.
        useChatStore
            .getState()
            .appendTextDelta(firstAssistant, "!", first.id);

        expect(textOf(useChatStore.getState().messages[0])).toBe("second");
        expect(textOf(chatSlice(first.id).messages[0])).toBe("first!");
        expect(chatSlice(first.id).isStreaming).toBe(true);
        expect(chatSlice(second.id).isStreaming).toBe(true);
    });

    test("switching back restores the background transcript", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useChatStore.getState().activate(first.id, null);
        useTabStore.getState().select(first.id);
        const id = useChatStore.getState().startAssistantMessage(first.id);
        useChatStore.getState().appendTextDelta(id, "kept", first.id);
        useChatStore.getState().completeStream(first.id);

        useChatStore.getState().activate(second.id, first.id);
        useTabStore.getState().select(second.id);

        useChatStore.getState().activate(first.id, second.id);
        useTabStore.getState().select(first.id);

        expect(textOf(useChatStore.getState().messages[0])).toBe("kept");
        expect(useChatStore.getState().isStreaming).toBe(false);
    });

    test("a stream for a closed tab is dropped", () => {
        const first = useTabStore.getState().create();
        const second = useTabStore.getState().create();
        useChatStore.getState().activate(first.id, null);
        useTabStore.getState().select(first.id);
        const id = useChatStore.getState().startAssistantMessage(first.id);

        useTabStore.getState().close(second.id);
        useChatStore.getState().remove(second.id);

        useChatStore.getState().appendTextDelta(id, "late", second.id);
        expect(chatSlice(second.id).messages).toEqual([]);
    });

    test("a silent retry clear does not replace equal state", () => {
        const tab = useTabStore.getState().create();
        useChatStore.getState().activate(tab.id, null);
        useTabStore.getState().select(tab.id);
        useChatStore.getState().setRetry(null, tab.id);
        expect(useChatStore.getState().retry).toBeNull();
    });
});
