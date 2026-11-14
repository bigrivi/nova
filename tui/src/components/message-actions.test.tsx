import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { AppProvider } = await import("../context/app.tsx");
const { MessageActionsScreen } = await import("./screens/MessageActionsScreen.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { useScreenStore } = await import("../stores/screen-store.ts");

afterEach(() => {
    useScreenStore.setState({ current: null });
    useChatStore.setState({ messages: [], sessionId: null, isStreaming: false });
});

async function openActions(text: string) {
    useChatStore.setState({ sessionId: "s1", isStreaming: false });
    const setup = await testRender(
        <AppProvider>
            <MessageActionsScreen messageId="m1" text={text} />
        </AppProvider>,
        { width: 80, height: 24 },
    );
    await settle(setup);
    return setup;
}

async function settle(setup: { flush: () => Promise<void> }) {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

test("the menu offers edit, copy and fork", async () => {
    const setup = await openActions("hello there");
    const frame = setup.captureCharFrame();
    expect(frame).toContain("Message Actions");
    expect(frame).toContain("Edit this question");
    expect(frame).toContain("Copy text");
    expect(frame).toContain("Fork from here");
});

test("a message with a code block offers to copy it", async () => {
    const setup = await openActions("look:\n```ts\nconst a = 1;\n```");
    const frame = setup.captureCharFrame();
    expect(frame).toContain("Copy code block");
});

test("a message without code offers no code action", async () => {
    const setup = await openActions("just prose");
    const frame = setup.captureCharFrame();
    expect(frame).not.toContain("Copy code block");
});
