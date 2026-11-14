import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { App } = await import("../App.tsx");
const { AppProvider } = await import("../../context/app.tsx");
const { useChatStore } = await import("../../stores/chat-store.ts");
const { useCtxStore } = await import("../../stores/ctx-store.ts");
const { useSidebarStore } = await import("../../stores/sidebar-store.ts");
const { useTodoStore } = await import("../../stores/todo-store.ts");

const TODOS = [
    { content: "wire the panel", status: "in_progress" as const, priority: "high" as const },
    { content: "ship it", status: "pending" as const, priority: "low" as const },
];

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
}

async function render(width: number) {
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width, height: 30 },
    );
    await settle(setup);
    return setup;
}

function seed(open: boolean): void {
    useTodoStore.setState({ todos: TODOS });
    useChatStore.setState({
        messages: [
            {
                id: "m1",
                role: "user",
                status: "done",
                parts: [{ type: "text", text: "hello" }],
            },
        ],
        sessionId: "s1",
        isStreaming: false,
    });
    useSidebarStore.setState({ open });
}

afterEach(() => {
    useSidebarStore.setState({ open: false });
    useTodoStore.setState({ todos: [] });
    useCtxStore.getState().clear();
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: "",
        model: "",
    });
});

test("a wide terminal docks the panel beside the transcript", async () => {
    seed(true);
    const setup = await render(120);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    expect(frame).toContain("wire the panel");
    // Both panes are on screen: the panel does not cover the transcript.
    expect(frame).toContain("Nova TUI");
});

test("a narrow terminal gives the panel the whole screen", async () => {
    seed(true);
    const setup = await render(80);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    expect(frame).toContain("wire the panel");
    expect(frame).not.toContain("Nova TUI");
});

test("the panel stays closed on a narrow terminal", async () => {
    seed(false);
    const setup = await render(80);
    expect(setup.captureCharFrame()).not.toContain("wire the panel");
    setup.renderer.destroy();
});

test("ctrl+b closes and reopens the panel", async () => {
    seed(false);
    const setup = await render(120);

    // Open by default on a wide terminal.
    expect(setup.captureCharFrame()).toContain("wire the panel");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x02"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).not.toContain("wire the panel");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x02"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("wire the panel");
    setup.renderer.destroy();
});

test("the todo counter counts settled items", async () => {
    useTodoStore.setState({
        todos: [
            { content: "first task", status: "completed", priority: "high" },
            { content: "second task", status: "pending", priority: "low" },
        ],
    });
    useChatStore.setState({ messages: [], sessionId: "s1", isStreaming: false });
    useSidebarStore.setState({ open: true });

    const setup = await render(120);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    expect(frame).toContain("(1/2)");
});

test("context usage leads the panel body", async () => {
    seed(true);
    const setup = await render(120);

    // Seed the context window after mount: the status bar's own one-shot read
    // would otherwise clobber (or supply) the value depending on the backend.
    await act(async () => {
        useCtxStore.getState().setCtx(387451, 1000000, 39);
    });
    await settle(setup);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    const lines = frame.split("\n");
    const tokenLine = lines.findIndex((line) => line.includes("387,451 tokens"));
    const percentLine = lines.findIndex((line) => line.includes("39% used"));
    const todoLine = lines.findIndex((line) => line.includes("wire the panel"));
    expect(tokenLine).toBeGreaterThan(-1);
    expect(percentLine).toBe(tokenLine + 1);
    // Above every other section.
    expect(tokenLine).toBeLessThan(todoLine);
});

test("a draft survives a fullscreen panel opening and closing", async () => {
    seed(false);
    // Narrow: the panel covers the screen, so the composer stays mounted under it.
    const setup = await render(80);

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("draft text"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("draft text");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x02"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("wire the panel");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x02"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("draft text");
    setup.renderer.destroy();
});
