import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { App } = await import("./App.tsx");
const { AppProvider } = await import("../context/app.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { useScreenStore } = await import("../stores/screen-store.ts");

const LONG = Array.from({ length: 30 }, (_, index) => ({
    id: `m${index}`,
    role: "user" as const,
    status: "done" as const,
    parts: [{ type: "text" as const, text: `message ${index}` }],
}));

afterEach(() => {
    useScreenStore.setState({ current: null });
    useChatStore.setState({ messages: [], sessionId: null, isStreaming: false });
});

async function transcript(width = 70, height = 20) {
    useChatStore.setState({
        messages: LONG,
        sessionId: "s1",
        isStreaming: false,
        provider: "test",
        model: "test",
    });
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width, height },
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

test("the hint is hidden while the transcript is at the bottom", async () => {
    const setup = await transcript();
    const frame = setup.captureCharFrame();
    expect(frame).toContain("message 29");
    expect(frame).not.toContain("Jump to latest");
});

test("scrolling up shows a right-aligned jump hint, and clicking it returns", async () => {
    const setup = await transcript();
    await act(async () => {
        await setup.mockMouse.scroll(20, 10, "up");
    });
    await settle(setup);

    const scrolled = setup.captureCharFrame().split("\n");
    const row = scrolled.findIndex((line) => line.includes("Jump to latest"));
    expect(row).toBeGreaterThan(0);
    expect(scrolled[row]!.indexOf("Jump to latest")).toBeGreaterThan(30);

    await act(async () => {
        await setup.mockMouse.click(scrolled[row]!.indexOf("Jump to latest") + 2, row);
    });
    await settle(setup);

    const back = setup.captureCharFrame();
    expect(back).not.toContain("Jump to latest");
    expect(back).toContain("message 29");
});

test("the hint occupies the single row directly above the composer", async () => {
    const setup = await transcript();
    await act(async () => {
        await setup.mockMouse.scroll(20, 10, "up");
    });
    await settle(setup);

    const lines = setup.captureCharFrame().split("\n");
    const hint = lines.findIndex((line) => line.includes("Jump to latest"));
    expect(lines[hint + 1]).toContain("───");
    expect(lines[hint + 2]).toContain("essage Nova");
});
