import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { App } = await import("../App.tsx");
const { AppProvider } = await import("../../context/app.tsx");
const { useChatStore } = await import("../../stores/chat-store.ts");
const { useCtxStore } = await import("../../stores/ctx-store.ts");
const { useSidebarStore } = await import("../../stores/sidebar-store.ts");
const { useTabStore } = await import("../../stores/tab-store.ts");
const { useTodoStore } = await import("../../stores/todo-store.ts");
const { useUsageStore } = await import("../../stores/usage-store.ts");

const TODOS = [
    { content: "wire the panel", status: "in_progress" as const, priority: "high" as const },
    { content: "ship it", status: "pending" as const, priority: "low" as const },
];

function stats(cost: number, turns: number) {
    return {
        scope: "session" as const,
        days: null,
        since: null,
        tokens: { input: 0, output: 0, cache_read: 0, total: 0 },
        cost: { total: cost, priced: true, unpriced_models: 0 },
        messages: 1,
        by_model: [],
        session: { turns, messages: 1, started_at: 0, updated_at: 0 },
    };
}

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
    useTodoStore.setState({ byId: { s1: TODOS } });
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
    useTodoStore.setState({ byId: {} });
    useTabStore.getState().reset();
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

test("a narrow terminal has no room to dock the panel", async () => {
    seed(true);
    const setup = await render(80);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    // 40 columns of panel beside 72 columns of transcript do not fit, and the
    // panel is not painted over the transcript instead.
    expect(frame).not.toContain("wire the panel");
    expect(frame).toContain("hello");
});

test("the tab strip spans the terminal above the docked panel", async () => {
    seed(true);
    for (const id of ["s1", "s2", "s3", "s4", "s5", "s6"]) {
        useTabStore.getState().create({ sessionId: id, title: `TAB-${id}` });
    }
    const setup = await render(120);
    const lines = setup.captureCharFrame().split("\n");
    setup.renderer.destroy();

    // The strip owns the first row and runs the whole width, so the panel
    // starts one row lower instead of shortening it. Docked at 120 columns the
    // panel starts at 80, and a strip laid out for the transcript column alone
    // could not paint a tab past that.
    const strip = lines.findIndex((line) => line.includes("TAB-s1"));
    const panel = lines.findIndex((line) => line.includes("wire the panel"));
    expect(strip).toBe(0);
    expect(panel).toBeGreaterThan(strip);
    expect(lines[0]!.slice(80).trim()).not.toBe("");
});

test("the docked panel is not painted in the user bubble's colour", async () => {
    seed(true);
    const setup = await render(120);
    const frame = setup.captureCharFrame();
    const spans = setup.captureSpans() as unknown as {
        lines: { spans: { text: string; bg: { buffer: ArrayLike<number> } }[] }[];
    };
    const rowOf = (text: string) =>
        frame.split("\n").findIndex((line) => line.includes(text));
    const bgOf = (row: number, text: string) =>
        Array.from(
            spans.lines[row]!.spans.find((span) => span.text.includes(text))!
                .bg.buffer,
        );
    const panelBg = bgOf(rowOf("wire the panel"), "wire the panel");
    const bubbleBg = bgOf(rowOf("hello"), "hello");
    setup.renderer.destroy();

    // Both were `background.raised`, so the strip read as one tall message.
    expect(panelBg).not.toEqual(bubbleBg);
});

test("the launch screen keeps the panel away", async () => {
    // No session yet: this is the launch screen.
    useTodoStore.setState({ byId: { s1: TODOS } });
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
    });
    useSidebarStore.setState({ open: true });

    const setup = await render(120);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    // The panel would show the todo list; the launch screen must not.
    expect(frame).not.toContain("wire the panel");
    // The card is drawn, centred in the whole terminal.
    expect(frame).toContain("╭");
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
        byId: {
            s1: [
                { content: "first task", status: "completed", priority: "high" },
                { content: "second task", status: "pending", priority: "low" },
            ],
        },
    });
    useChatStore.setState({ messages: [], sessionId: "s1", isStreaming: false });
    useSidebarStore.setState({ open: true });

    const setup = await render(120);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    expect(frame).toContain("(1/2)");
});

test("todo rows use the bracketed markers", async () => {
    seed(true);
    const setup = await render(120);
    const frame = setup.captureCharFrame();
    setup.renderer.destroy();

    expect(frame).toContain("[•] wire the panel");
    expect(frame).toContain("[ ] ship it");
});

test("the panel shows only the active session's todos", async () => {
    useTodoStore.setState({
        byId: {
            s1: [
                { content: "first session task", status: "pending", priority: "low" },
            ],
            s2: [
                { content: "second session task", status: "in_progress", priority: "high" },
            ],
        },
    });
    useChatStore.setState({ messages: [], sessionId: "s1", isStreaming: false });
    useSidebarStore.setState({ open: true });

    const setup = await render(120);
    expect(setup.captureCharFrame()).toContain("first session task");
    expect(setup.captureCharFrame()).not.toContain("second session task");

    await act(async () => {
        useChatStore.setState({ sessionId: "s2" });
    });
    await settle(setup);

    expect(setup.captureCharFrame()).toContain("second session task");
    expect(setup.captureCharFrame()).not.toContain("first session task");
    setup.renderer.destroy();
});

test("switching sessions reads each session's cached context and spend", async () => {
    useCtxStore.setState({
        byId: {
            s1: { used: 111, limit: 1000, percent: 11 },
            s2: { used: 222, limit: 1000, percent: 22 },
        },
    });
    useUsageStore.setState({ byId: { s1: stats(1, 2), s2: stats(3, 4) } });
    useChatStore.setState({ messages: [], sessionId: "s1", isStreaming: false });
    useSidebarStore.setState({ open: true });

    const setup = await render(120);
    expect(setup.captureCharFrame()).toContain("111 tokens");
    expect(setup.captureCharFrame()).toContain("$1.00 spent · 2 turns");

    await act(async () => {
        useChatStore.setState({ sessionId: "s2" });
    });
    await settle(setup);

    const frame = setup.captureCharFrame();
    expect(frame).toContain("222 tokens");
    expect(frame).toContain("$3.00 spent · 4 turns");
    expect(frame).not.toContain("111 tokens");
    setup.renderer.destroy();
});

test("context usage leads the panel body", async () => {
    seed(true);
    const setup = await render(120);

    // Seed the context window after mount: the status bar's own one-shot read
    // would otherwise clobber (or supply) the value depending on the backend.
    await act(async () => {
        useCtxStore.getState().setCtx("s1", 387451, 1000000, 39);
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

test("a draft survives the panel opening and closing", async () => {
    seed(true);
    const setup = await render(120);

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("draft text"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("draft text");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x02"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).not.toContain("wire the panel");
    expect(setup.captureCharFrame()).toContain("draft text");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x02"));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("wire the panel");
    expect(setup.captureCharFrame()).toContain("draft text");
    setup.renderer.destroy();
});
