import { expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { UserMessage } = await import("./UserMessage.tsx");

test("an attachment shows under the bubble as a name, not as data", async () => {
    const setup = await testRender(
        <UserMessage
            message={{
                id: "m1",
                role: "user",
                status: "done",
                parts: [
                    { type: "text", text: "look at this", images: ["shot.png"] },
                ],
            }}
        />,
        { width: 60, height: 10 },
    );
    await setup.flush();
    const frame = setup.captureCharFrame();
    expect(frame).toContain("look at this");
    expect(frame).toContain("▧ shot.png");
    expect(frame).not.toContain("base64");
});

test("a message without attachments has no chip", async () => {
    const setup = await testRender(
        <UserMessage
            message={{
                id: "m2",
                role: "user",
                status: "done",
                parts: [{ type: "text", text: "hello" }],
            }}
        />,
        { width: 60, height: 8 },
    );
    await setup.flush();
    expect(setup.captureCharFrame()).not.toContain("▧");
});
