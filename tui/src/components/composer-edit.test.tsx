import { afterEach, expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { AppProvider } = await import("../context/app.tsx");
const { Composer } = await import("./Composer.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { useEditStore } = await import("../stores/edit-store.ts");

const sent: { message: string }[] = [];
const edited: { messageId: string; text: string }[] = [];

mock.module("../stream/chat-stream.ts", () => ({
    runChatStream: async (options: { message: string }) => {
        sent.push(options);
    },
    interruptChat: async () => {},
    editAndResend: async (messageId: string, text: string) => {
        edited.push({ messageId, text });
    },
}));

async function composer() {
    const setup = await testRender(
        <AppProvider>
            <Composer onCommand={() => {}} />
        </AppProvider>,
        { width: 90, height: 12 },
    );
    await settle(setup);
    return setup;
}

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 3; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

afterEach(() => {
    sent.length = 0;
    edited.length = 0;
    useEditStore.getState().clear();
    useChatStore.setState({ isStreaming: false, sessionId: null });
});

test("the question being edited lands in the composer, with a banner", async () => {
    useEditStore.getState().set("msg-1", "the old question");
    const setup = await composer();
    await settle(setup);

    const frame = setup.captureCharFrame();
    expect(frame).toContain("editing an earlier question");
    expect(frame).toContain("the old question");
});

test("sending it edits the question instead of asking a new one", async () => {
    useEditStore.getState().set("msg-1", "the old question");
    const setup = await composer();
    await settle(setup);

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("!"));
    });
    await settle(setup);
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\r"));
    });
    await settle(setup);

    expect(edited).toEqual([{ messageId: "msg-1", text: "the old question!" }]);
    expect(sent).toEqual([]);
    // The edit is over: the composer is free again.
    expect(useEditStore.getState().messageId).toBeNull();
});

test("escape abandons the edit and keeps the question as it was", async () => {
    useEditStore.getState().set("msg-1", "the old question");
    const setup = await composer();
    await settle(setup);

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x1b"));
    });
    await settle(setup);

    expect(useEditStore.getState().messageId).toBeNull();
    expect(edited).toEqual([]);
    expect(sent).toEqual([]);
});
