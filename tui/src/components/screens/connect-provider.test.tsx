import { afterEach, expect, mock, test } from "bun:test";

// No backend: presets come from the stubbed API, and the app's startup effects
// are stubbed out so nothing races the render.
const deleted: string[] = [];

const api = await import("../../api/nova-api.ts");
mock.module("../../api/nova-api.ts", () => ({
    ...api,
    getAgent: async () => null,
    listSessions: async () => [],
    // OpenAI is already connected, so its row must carry the check mark.
    listProviders: async () => [
        {
            key: "openai",
            name: "OpenAI",
            type: "openai-compatible",
            authenticated: true,
        },
        {
            key: "inferx",
            name: "Inferx",
            type: "openai-compatible",
            authenticated: false,
        },
    ],
    // The app refreshes provider catalogues on launch; a render test must not
    // reach for a backend that is not there.
    syncProviderModels: async () => ({ synced: [], failed: {} }),
    deleteProvider: async (key: string) => {
        deleted.push(key);
        return [];
    },
    listProviderPresets: async () => [
        {
            id: "ollama",
            label: "Ollama (local)",
            type: "ollama",
            base_url: "http://localhost:11434",
            key_env: null,
            note: "",
        },
        {
            id: "openai",
            label: "OpenAI",
            type: "openai-compatible",
            base_url: "https://api.openai.com/v1",
            key_env: "OPENAI_API_KEY",
            note: "",
        },
        {
            id: "acme",
            label: "Acme",
            type: "openai-compatible",
            base_url: "https://acme.example/v1",
            key_env: "ACME_API_KEY",
            note: "",
        },
    ],
}));

const { testRender } = await import("@opentui/react/test-utils");
const { App } = await import("../App.tsx");
const { AppProvider } = await import("../../context/app.tsx");
const { useScreenStore } = await import("../../stores/screen-store.ts");

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
}

async function render() {
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width: 100, height: 30 },
    );
    await settle(setup);
    return setup;
}

afterEach(() => {
    useScreenStore.setState({ current: null });
});

test("connecting offers the presets and the custom escape hatch", async () => {
    useScreenStore.setState({ current: { kind: "connect-provider" } });

    const setup = await render();
    const frame = setup.captureCharFrame();

    // The shared searchable list, so 44 vendors are reachable by typing.
    expect(frame).toContain("Connect a provider");
    expect(frame).toContain("Filter");
    expect(frame).toContain("Ollama (local)");
    expect(frame).toContain("Custom (any OpenAI-compatible endpoint)");
    // Everything configured is grouped under "Connected" and marked, so
    // choosing one again reads as "rotate the key" rather than "this fails".
    // The check mark means Nova holds a key on this machine, not that the
    // provider merely exists in config.json.
    expect(frame).toContain("✓ OpenAI");
    expect(frame).toContain("Configured");
});


test("a connected provider opens on its own panel and can be disconnected", async () => {
    const { act } = await import("react");
    deleted.length = 0;
    useScreenStore.setState({ current: { kind: "connect-provider" } });
    const setup = await render();

    await act(async () => {
        await setup.mockInput.typeText("openai");
    });
    await settle(setup);
    await act(async () => {
        setup.mockInput.pressEnter();
    });
    await settle(setup);

    const panel = setup.captureCharFrame();
    expect(panel).toContain("● Connected · API key");
    // Deleting is a modified key on purpose: a bare letter would be typed into
    // the filter instead.
    expect(panel).toContain("ctrl+d disconnect");

    await act(async () => {
        setup.mockInput.pressKey("d", { ctrl: true });
    });
    await settle(setup);

    expect(deleted).toEqual(["openai"]);
});


test("title, group headers and rows share one left edge", async () => {
    useScreenStore.setState({ current: { kind: "connect-provider" } });

    const setup = await render();
    const lines = setup.captureCharFrame().split("\n");
    const columnOf = (needle: string): number => {
        const line = lines.find((candidate) => candidate.includes(needle));
        expect(line).toBeDefined();
        return line!.indexOf(needle);
    };

    const title = columnOf("Connect a provider");
    const header = columnOf("Available");
    const row = columnOf("Ollama (local)");

    expect(header).toBe(title);
    expect(row).toBe(title);
});


test("the filter matches the name, not the wire type", async () => {
    const { act } = await import("react");
    useScreenStore.setState({ current: { kind: "connect-provider" } });
    const setup = await render();

    await act(async () => {
        await setup.mockInput.typeText("openai-compatible");
    });
    await settle(setup);

    const frame = setup.captureCharFrame();
    // Only "Custom (any OpenAI-compatible endpoint)" has that text in its
    // *name*. Matching the wire type would also pull in OpenAI and Acme, which
    // is exactly what this test refuses.
    expect(frame).toContain("1/1");
    expect(frame).not.toContain("Acme");
});
