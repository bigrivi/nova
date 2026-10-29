import { expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { AppProvider } = await import("../context/app.tsx");
const { ComposerShell } = await import("../test-utils/composer-harness.tsx");
const { useMenuStore } = await import("../stores/menu-store.ts");
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
