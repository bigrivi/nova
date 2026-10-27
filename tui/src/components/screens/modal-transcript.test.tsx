import { expect, test } from "bun:test";

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { MessageList } = await import("../MessageList.tsx");
const { SearchableList } = await import("./SearchableList.tsx");
const { useChatStore } = await import("../../stores/chat-store.ts");
const { useScreenStore } = await import("../../stores/screen-store.ts");
const { AppProvider } = await import("../../context/app.tsx");

/** Wide (CJK) glyphs are the canary: an overlay that composites per cell loses
 *  them while ASCII survives, which is what a dimming fill used to do. */
const CJK = "搜到了。信息主要来自它的官方 PR 稿和第三方报道，给你梳理一下：";
const ASCII = "Search results came from the official press release";

function Scene() {
    const open = useScreenStore((state) => state.current !== null);
    return (
        <box width="100%" height="100%" flexDirection="column">
            <MessageList />
            {open ? (
                <SearchableList
                    title="Models"
                    items={[{ label: "Agnes 3.0 Flash", value: "a" }]}
                    onSelect={() => {}}
                    onClose={() => {}}
                />
            ) : null}
        </box>
    );
}

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

async function run(): Promise<{
    before: string[];
    after: string[];
}> {
    useScreenStore.setState({ current: null });
    useChatStore.setState({
        messages: [
            {
                id: "m1",
                role: "assistant",
                status: "done",
                parts: [{ type: "text", text: `${CJK}\n\n${ASCII}` }],
            },
        ],
    });
    const setup = await testRender(
        <AppProvider>
            <Scene />
        </AppProvider>,
        { width: 100, height: 24 },
    );
    await settle(setup);
    const before = setup.captureCharFrame().split("\n");
    act(() => useScreenStore.setState({ current: { kind: "models" } }));
    await settle(setup);
    const after = setup.captureCharFrame().split("\n");
    return { before, after };
}

test("opening a screen keeps wide glyphs and ASCII outside the panel", async () => {
    const { before, after } = await run();
    expect(before.join("\n")).toContain(CJK);
    // the panel covers the middle of the line, so only the head stays visible
    expect(after.join("\n")).toContain("● 搜到了。信息主要来自");
    expect(after.join("\n")).toContain("Search results came f");
});

test("rows above the panel are left exactly as they were", async () => {
    const { before, after } = await run();
    const title = after.findIndex((line) => line.includes("Models"));
    expect(title).toBeGreaterThan(0);
    for (let y = 0; y < title - 2; y += 1) {
        expect(after[y]).toBe(before[y]);
    }
});
