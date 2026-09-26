import { beforeEach, describe, expect, it } from "vitest";

import { useComposerStore } from "./composer-store";

beforeEach(() => {
    useComposerStore.setState({ text: "" });
});

describe("composer draft", () => {
    it("keeps the latest keystroke", () => {
        const store = useComposerStore.getState();
        store.setText("h");
        store.setText("he");
        store.setText("hello");

        expect(useComposerStore.getState().text).toBe("hello");
    });

    it("clears on new chat and on submit", () => {
        const store = useComposerStore.getState();
        store.setText("draft to discard");
        store.clear();

        expect(useComposerStore.getState().text).toBe("");
    });

    it("notifies subscribers on every change", () => {
        const seen: string[] = [];
        const unsubscribe = useComposerStore.subscribe((state) =>
            seen.push(state.text),
        );
        useComposerStore.getState().setText("a");
        useComposerStore.getState().setText("ab");
        unsubscribe();

        expect(seen).toEqual(["a", "ab"]);
    });
});
