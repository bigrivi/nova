import { afterEach, expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { UserMessage } = await import("./UserMessage.tsx");
const { useScreenStore } = await import("../stores/screen-store.ts");

function click(
    setup: {
        renderer: { stdin: { emit: (event: string, data: Buffer) => void } };
        flush: () => Promise<void>;
    },
    row: number,
    column = 5,
): Promise<void> {
    return (async () => {
        await act(async () => {
            setup.renderer.stdin.emit("data", Buffer.from(`\u001b[<0;${column};${row}M`));
        });
        await setup.flush();
        await act(async () => {
            setup.renderer.stdin.emit("data", Buffer.from(`\u001b[<0;${column};${row}m`));
        });
        await setup.flush();
    })();
}

afterEach(() => {
    useScreenStore.getState().close();
});

test("clicking a user message opens the actions screen", async () => {
    useScreenStore.getState().close();
    const setup = await testRender(
        <UserMessage
            message={{
                id: "m1",
                role: "user",
                status: "done",
                parts: [{ type: "text", text: "hello" }],
            }}
        />,
        { width: 60, height: 10 },
    );
    await setup.flush();
    await click(setup, 3, 5);
    await setup.flush();
    expect(useScreenStore.getState().current).toEqual({
        kind: "message-actions",
        messageId: "m1",
        text: "hello",
    });
});
