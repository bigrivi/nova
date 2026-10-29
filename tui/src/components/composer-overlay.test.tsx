import { afterEach, expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { AppProvider } = await import("../context/app.tsx");
const { ComposerShell } = await import("../test-utils/composer-harness.tsx");
const { useMenuStore } = await import("../stores/menu-store.ts");
const { MenuOverlay } = await import("./MenuOverlay.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");

mock.module("../stream/chat-stream.ts", () => ({
    runChatStream: async () => {},
    interruptChat: async () => {},
}));

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 3; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

async function type(
    setup: { renderer: { stdin: { emit: (event: string, data: Buffer) => void } } },
    text: string,
): Promise<void> {
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(text));
    });
}

function rowOf(frame: string, needle: string): number {
    return frame.split("\n").findIndex((line) => line.includes(needle));
}

test("the menu renders above the input, clear of the status bar", async () => {
    useChatStore.setState({ isStreaming: false, sessionId: null });
    // Launch layout: one centred card, nothing else on screen.
    const setup = await testRender(
        <AppProvider>
            <ComposerShell variant="card" height={24} />
        </AppProvider>,
        { width: 80, height: 24 },
    );
    await settle(setup);

    await type(setup, "/");
    await settle(setup);

    // The composer owns the state; the root owns the layer.
    const state = useMenuStore.getState();
    expect(state.items.length).toBeGreaterThan(0);
    expect(state.height).toBeGreaterThan(0);

    const frame = setup.captureCharFrame();
    const menuRow = rowOf(frame, "/new");
    expect(menuRow).toBeGreaterThan(0);
    // Above the input, so the menu never covers what is being typed.
    expect(menuRow).toBeLessThan(rowOf(frame, ">"));
});

test("closing the composer clears the published menu", async () => {
    const setup = await testRender(
        <AppProvider>
            <ComposerShell height={24} />
        </AppProvider>,
        { width: 80, height: 24 },
    );
    await settle(setup);

    await type(setup, "/");
    await settle(setup);
    expect(useMenuStore.getState().items.length).toBeGreaterThan(0);

    await type(setup, "\u001b");
    await settle(setup);
    // A menu that outlives its composer would hang over the next screen.
    expect(useMenuStore.getState().items).toEqual([]);
});

test("the menu scrolls to keep a selection below the fold visible", async () => {
    useMenuStore.getState().show(
        Array.from({ length: 20 }, (_, index) => ({
            id: `c${index}`,
            label: `command ${index}`,
            description: "",
            usage: `/command-${index}`,
            aliases: [],
        })),
        17,
        4 + 6,
        { x: 0, y: 20, width: 80, edgeY: 20 },
        1,
    );

    const setup = await testRender(
        <AppProvider>
            <box flexDirection="column" width="100%" height={24}>
                <MenuOverlay anchorY={20} anchorX={0} anchorWidth={80} />
            </box>
        </AppProvider>,
        { width: 80, height: 24 },
    );
    await settle(setup);

    const frame = setup.captureCharFrame();
    // A sliced window would show items 0-5 and hide the selection entirely.
    expect(frame).toContain("/command-17");
    expect(frame).not.toContain("/command-0");
});

afterEach(() => {
    // The menu store is process-wide: a seeded menu would float over every later
    // test that renders App.
    useMenuStore.getState().clear();
});

/** SGR mouse press+release at one cell — what a terminal sends for a click. */
async function click(
    setup: {
        renderer: { stdin: { emit: (event: string, data: Buffer) => void } };
        flush: () => Promise<void>;
    },
    row: number,
    column = 5,
): Promise<void> {
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(`\u001b[<0;${column};${row}M`));
    });
    await step(setup);
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(`\u001b[<0;${column};${row}m`));
    });
    await step(setup);
}

async function stableFrame(setup: {
    flush: () => Promise<void>;
    captureCharFrame: () => string;
}): Promise<string[]> {
    let previous = setup.captureCharFrame();
    for (let attempt = 0; attempt < 10; attempt += 1) {
        await step(setup);
        const next = setup.captureCharFrame();
        if (next === previous) return next.split("\n");
        previous = next;
    }
    return previous.split("\n");
}

async function step(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 3; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
}

test("clicking a command row runs it", async () => {
    const commands: string[] = [];
    const setup = await testRender(
        <AppProvider>
            <ComposerShell
                height={24}
                onCommand={(id) => {
                    commands.push(id);
                }}
            />
        </AppProvider>,
        { width: 90, height: 24 },
    );
    await settle(setup);

    await type(setup, "/");
    await settle(setup);
    // Wait for the menu to stop moving: the composer publishes its measured
    // anchor on a 50 ms poll, so the first frame after opening can be one row
    // off, and a click on a stale row lands nowhere.
    const rows = await stableFrame(setup);
    const row = rows.findIndex((line) => line.includes("/sessions"));
    expect(row).toBeGreaterThan(0);

    await click(setup, row + 1);
    await settle(setup);

    // The pointer picks the row it landed on, not the highlighted one.
    expect(commands).toEqual(["sessions"]);
});
