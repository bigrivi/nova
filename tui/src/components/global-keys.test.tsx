import { afterEach, expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { App } = await import("./App.tsx");
const { AppProvider } = await import("../context/app.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { useScreenStore } = await import("../stores/screen-store.ts");
const { useTabStore } = await import("../stores/tab-store.ts");

/** Control characters: ctrl+w = 0x17, ctrl+t = 0x14, ctrl+c = 0x03. */
async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

async function render(onExit: () => void) {
    const setup = await testRender(
        <AppProvider>
            <App onExit={onExit} />
        </AppProvider>,
        { width: 100, height: 24 },
    );
    await settle(setup);
    return setup;
}

function press(setup: { renderer: { stdin: { emit: (event: string, data: Buffer) => void } } }, byte: string): void {
    act(() => {
        setup.renderer.stdin.emit("data", Buffer.from(byte));
    });
}

afterEach(() => {
    useTabStore.getState().reset();
    useScreenStore.setState({ current: null });
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: "",
        model: "",
    });
});

test("ctrl+w closes the tab, and a screen takes the key over", async () => {
    const setup = await render(() => {});
    const tab = useTabStore.getState().create({ sessionId: "s2" });
    useTabStore.getState().select(tab.id);
    expect(useTabStore.getState().tabs.length).toBe(1);

    press(setup, "\x17");
    await settle(setup);
    expect(useTabStore.getState().tabs.length).toBe(0);

    const other = useTabStore.getState().create({ sessionId: "s3" });
    useTabStore.getState().select(other.id);
    act(() => useScreenStore.setState({ current: { kind: "models" } }));
    press(setup, "\x17");
    await settle(setup);
    expect(useTabStore.getState().tabs.length).toBe(1);
});

test("ctrl+t opens a draft tab, and a screen takes the key over", async () => {
    const setup = await render(() => {});
    press(setup, "\x14");
    await settle(setup);
    expect(useTabStore.getState().tabs.length).toBe(1);

    act(() => useScreenStore.setState({ current: { kind: "models" } }));
    press(setup, "\x14");
    await settle(setup);
    expect(useTabStore.getState().tabs.length).toBe(1);
});

test("ctrl+c exits, with and without a screen open", async () => {
    let exits = 0;
    const setup = await render(() => {
        exits += 1;
    });

    press(setup, "\x03");
    await settle(setup);
    expect(exits).toBe(1);

    act(() => useScreenStore.setState({ current: { kind: "models" } }));
    press(setup, "\x03");
    await settle(setup);
    expect(exits).toBe(1);
});
