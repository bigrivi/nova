import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { App } = await import("../App.tsx");
const { AppProvider } = await import("../../context/app.tsx");
const { useChatStore } = await import("../../stores/chat-store.ts");
const { useScreenStore } = await import("../../stores/screen-store.ts");

afterEach(() => {
    useScreenStore.setState({ current: null });
    useChatStore.setState({ messages: [], sessionId: null, isStreaming: false });
});

async function dialogAt(width: number, height: number): Promise<string> {
    useChatStore.setState({
        messages: [
            { id: "m1", role: "user", status: "done", parts: [{ type: "text", text: "hi" }] },
        ],
        sessionId: "s1",
    });
    useScreenStore.setState({ current: { kind: "models" } });
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width, height },
    );
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();
    return frame;
}

test("a dialog on a short terminal keeps its title and stays off the composer", async () => {
    for (const height of [16, 18, 22]) {
        const frame = await dialogAt(80, height);
        const lines = frame.split("\n");
        // the panel header must survive; it used to be clipped away
        expect({ height, title: lines.some((line) => line.includes("Models")) })
            .toMatchObject({ height });
        expect(frame).toContain("Models");
        // and the footer must stay on screen instead of spilling past it
        const footer = lines.findIndex((line) => line.includes("↑↓"));
        expect({ height, ok: footer >= 0 && footer < lines.length - 1 }).toMatchObject({
            height,
            ok: true,
        });
    }
});
