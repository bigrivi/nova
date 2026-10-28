import { afterEach, expect, mock, test } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { AppProvider } = await import("../context/app.tsx");
const { Composer } = await import("./Composer.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");

const submitted: { message: string; attachments?: unknown[] }[] = [];

mock.module("../stream/chat-stream.ts", () => ({
    runChatStream: async (options: { message: string; attachments?: unknown[] }) => {
        submitted.push(options);
    },
    interruptChat: async () => {},
}));

const PNG = Buffer.from("89504e470d0a1a0a", "hex");

function tempPng(name = "shot.png"): string {
    const dir = mkdtempSync(join(tmpdir(), "nova-composer-"));
    const path = join(dir, name);
    writeFileSync(path, PNG);
    return path;
}

async function composer() {
    const setup = await testRender(
        <AppProvider>
            <Composer onCommand={() => {}} />
        </AppProvider>,
        { width: 90, height: 12 },
    );
    await settle(setup);
    return setup;
}

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 3; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

function paste(text: string): string {
    return `\x1b[200~${text}\x1b[201~`;
}

afterEach(() => {
    submitted.length = 0;
    useChatStore.setState({ isStreaming: false, sessionId: null });
});

test("pasting an image path inserts a chip, not the path", async () => {
    const path = tempPng();
    const setup = await composer();
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(paste(`file://${path}`)));
    });
    await settle(setup);
    const frame = setup.captureCharFrame();
    expect(frame).toContain("▧ shot.png ×");
    expect(frame).not.toContain("/shot.png");
});

test("a non-image paste keeps the default text behaviour", async () => {
    const dir = mkdtempSync(join(tmpdir(), "nova-composer-"));
    const path = join(dir, "notes.txt");
    writeFileSync(path, "hello");
    const setup = await composer();
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(paste(path)));
    });
    await settle(setup);
    const frame = setup.captureCharFrame();
    expect(frame).toContain("notes.txt");
    expect(frame).not.toContain("▧");
});

test("backspace deletes the whole chip and its attachment", async () => {
    const path = tempPng();
    const setup = await composer();
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(paste(path)));
    });
    await settle(setup);
    expect(setup.captureCharFrame()).toContain("▧ shot.png ×");

    // The chip ends with the cursor; one backspace must remove all of it.
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\x7f"));
    });
    await settle(setup);
    const frame = setup.captureCharFrame();
    expect(frame).not.toContain("▧");
    expect(frame).not.toContain("shot.png");

    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("hello"));
    });
    await settle(setup);
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\r"));
    });
    await settle(setup);
    expect(submitted.at(-1)?.attachments).toEqual([]);
});

test("submitting sends the image and leaves the chip out of the message", async () => {
    const path = tempPng();
    const setup = await composer();
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from(paste(path)));
    });
    await settle(setup);
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("look at this"));
    });
    await settle(setup);
    await act(async () => {
        setup.renderer.stdin.emit("data", Buffer.from("\r"));
    });
    await settle(setup);

    const last = submitted.at(-1);
    expect(last?.message).toBe("look at this");
    expect(last?.message).not.toContain("▧");
    const attachments = last?.attachments as
        | { type: string; name: string; content: { image: string }[] }[]
        | undefined;
    expect(attachments?.[0]?.type).toBe("image");
    expect(attachments?.[0]?.name).toBe("shot.png");
    expect(attachments?.[0]?.content[0]?.image).toStartWith(
        "data:image/png;base64,",
    );
});
