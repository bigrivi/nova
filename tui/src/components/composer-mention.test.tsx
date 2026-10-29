import { afterEach, beforeEach, expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { AppProvider } = await import("../context/app.tsx");
const { ComposerShell } = await import("../test-utils/composer-harness.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { WORKSPACE_DIR } = await import("../workspace.ts");
const { useMenuStore } = await import("../stores/menu-store.ts");

const submitted: { message: string }[] = [];

mock.module("../stream/chat-stream.ts", () => ({
    runChatStream: async (options: { message: string }) => {
        submitted.push(options);
    },
    interruptChat: async () => {},
}));

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    // The candidate list arrives through an async readdir plus a store write, and
    // the suite runs files back to back — three short passes flaked under load.
    for (let pass = 0; pass < 8; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 40));
    }
}

beforeEach(() => {
    useMenuStore.getState().clear();
});

async function composer() {
    // The composer lives at the bottom of the screen, so the menu has room to
    // open above it — the same geometry the app uses.
    const setup = await testRender(
        <AppProvider>
            <ComposerShell height={24} />
        </AppProvider>,
        { width: 90, height: 24 },
    );
    await settle(setup);
    return setup;
}

async function type(
    setup: { renderer: { stdin: { emit: (event: string, data: Buffer) => void } } },
    text: string,
): Promise<void> {
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(text));
    });
}

afterEach(() => {
    submitted.length = 0;
    useChatStore.setState({ isStreaming: false, sessionId: null });
});

test("a path query lists the directory before its files", async () => {
    const setup = await composer();

    await type(setup, "@src/l");
    await settle(setup);

    // `src/lib` exists in the TUI package the tests run from, and a query with a
    // slash must not be crowded out by sub-agents.
    const frame = setup.captureCharFrame();
    expect(frame).toContain("@src/lib");
    expect(frame).not.toContain("@coder");
    expect(WORKSPACE_DIR.length).toBeGreaterThan(0);
});

test("Enter accepts the highlighted path instead of sending a bare @", async () => {
    const setup = await composer();

    await type(setup, "@src/l");
    await settle(setup);
    await type(setup, "\r");
    await settle(setup);

    // The reported bug: with the menu open, Enter sent `@` and the model asked
    // the user what they meant. Enter must complete instead.
    expect(submitted).toHaveLength(0);
    expect(setup.captureCharFrame()).toContain("@src/lib/");
});

test("Tab walks from a directory into a file, then Enter sends the path", async () => {
    const setup = await composer();

    await type(setup, "@src/l");
    await settle(setup);
    await type(setup, "\t");
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("@src/");

    await type(setup, "att");
    await settle(setup);
    await type(setup, "\t");
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("@src/lib/attachments");

    await type(setup, " explain\r");
    await settle(setup);

    expect(submitted.at(-1)?.message).toContain("@src/lib/attachments");
});

test("a menu that no longer matches the token does not rewrite it", async () => {
    const setup = await composer();

    await type(setup, "@");
    await settle(setup);
    await type(setup, "zzz\r");
    await settle(setup);

    // Whatever the stale list held, the sent text is what was typed.
    expect(submitted.at(-1)?.message).toContain("@zzz");
});

test("one backspace removes a whole accepted mention", async () => {
    const setup = await composer();

    await type(setup, "@src/l");
    await settle(setup);
    await type(setup, "\t");
    await settle(setup);
    await type(setup, "att");
    await settle(setup);
    await type(setup, "\t");
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("@src/lib/attachments");

    // A mention is one reference, not a string of characters.
    await type(setup, "\u007f");
    await settle(setup);

    const frame = setup.captureCharFrame();
    expect(frame).not.toContain("@src/lib/attachments");
    expect(frame).not.toContain("@src/lib/");
});

test("backspace mid-token still edits a half-typed directory", async () => {
    const setup = await composer();

    await type(setup, "@src/l");
    await settle(setup);
    await type(setup, "\t");
    await settle(setup);

    // `@src/lib/` was only a prefix, so ordinary editing must still work.
    await type(setup, "\u007f");
    await settle(setup);

    expect(setup.captureCharFrame()).toContain("@src/lib");
});
