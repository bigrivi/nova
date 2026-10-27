import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { App } = await import("../App.tsx");
const { AppProvider } = await import("../../context/app.tsx");
const { useChatStore } = await import("../../stores/chat-store.ts");
const { useScreenStore } = await import("../../stores/screen-store.ts");
const { LOGO_COMPACT } = await import("./NovaLogo.tsx");

const EMPTY = { messages: [], sessionId: null, isStreaming: false };

async function render(width = 100, height = 24) {
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width, height },
    );
    await settle(setup);
    return setup;
}

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
}

function padding(line: string): number {
    return line.length - line.trimStart().length;
}

afterEach(() => {
    useChatStore.setState({ ...EMPTY, provider: "", model: "" });
    useScreenStore.setState({ current: null });
});

test("an empty session shows the mark and a rounded composer card", async () => {
    useChatStore.setState(EMPTY);
    const setup = await render();
    const lines = setup.captureCharFrame().split("\n");
    expect(lines.some((line) => line.includes("█"))).toBe(true);
    expect(lines.some((line) => line.includes("╭"))).toBe(true);
    // no transcript banner while the launch screen is up
    expect(lines.some((line) => line.includes("Nova TUI"))).toBe(false);
});

test("the card is centred horizontally", async () => {
    useChatStore.setState(EMPTY);
    const setup = await render();
    const lines = setup.captureCharFrame().split("\n");
    const cardRow = lines.findIndex((line) => line.includes("╭"))!;
    const left = padding(lines[cardRow]!);
    const right = lines[cardRow]!.length - lines[cardRow]!.trimEnd().length;
    expect(Math.abs(left - right)).toBeLessThanOrEqual(1);
});

test("the composer keeps its draft when the session fills up", async () => {
    useChatStore.setState(EMPTY);
    const setup = await render();
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("draft text"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("draft text");

    act(() =>
        useChatStore.setState({
            sessionId: "s1",
            messages: [
                {
                    id: "m1",
                    role: "user",
                    status: "done",
                    parts: [{ type: "text", text: "hi" }],
                },
            ],
        }),
    );
    await settle(setup);
    const frame = setup.captureCharFrame();
    expect(frame).toContain("draft text");
    expect(frame).toContain("╭");
});

test("a loaded session with no messages does not show the launch screen", async () => {
    useChatStore.setState({ ...EMPTY, sessionId: "s1" });
    const setup = await render();
    const frame = setup.captureCharFrame();
    expect(frame).not.toContain("█");
    expect(frame).not.toContain("Ask anything");
});

test("a missing model is called out on the launch screen", async () => {
    useChatStore.setState(EMPTY);
    const setup = await render();
    // the startup effect may resolve the agent's model from the backend
    act(() => useChatStore.setState({ provider: "", model: "" }));
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("No model selected");

    act(() => useChatStore.setState({ provider: "openai", model: "gpt" }));
    await settle(setup);
    expect(setup.captureCharFrame()).not.toContain("No model selected");
});

test("the mark collapses on narrow terminals and hides on short ones", async () => {
    useChatStore.setState(EMPTY);
    const narrow = await render(50, 24);
    expect(narrow.captureCharFrame()).toContain(LOGO_COMPACT);

    const short = await render(100, 10);
    const frame = short.captureCharFrame();
    expect(frame).not.toContain("█");
    expect(frame).not.toContain(LOGO_COMPACT);
});
