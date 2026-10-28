import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { App } = await import("./App.tsx");
const { AppProvider } = await import("../context/app.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { useScreenStore } = await import("../stores/screen-store.ts");

afterEach(() => {
    useScreenStore.setState({ current: null });
    useChatStore.setState({ messages: [], sessionId: null, isStreaming: false });
});

test("the last message keeps a gap above the composer", async () => {
    useChatStore.setState({
        messages: [
            {
                id: "m1",
                role: "user",
                status: "done",
                parts: [{ type: "text", text: "last message" }],
            },
        ],
        sessionId: "s1",
        isStreaming: false,
        provider: "test",
        model: "test",
    });
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width: 70, height: 20 },
    );
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
    const lines = setup.captureCharFrame().split("\n");
    const message = lines.findIndex((line) => line.includes("last message"));
    const composerBorder = lines.findIndex(
        (line, index) => index > message && line.includes("───"),
    );
    expect(message).toBeGreaterThanOrEqual(0);
    expect(composerBorder).toBeGreaterThan(message);
    // The bubble already pads one row; the spacer under the scroll content adds
    // another, so the transcript never sits flush against the composer.
    expect(composerBorder - message - 1).toBeGreaterThanOrEqual(2);
});
