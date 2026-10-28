import { expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../../test-utils/mocked-theme.ts";

mock.module("../../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { ToolBlock } = await import("../ToolBlock.tsx");

async function frame(outputText: string): Promise<string> {
    const setup = await testRender(
        <ToolBlock
            part={{
                type: "tool-call",
                toolCallId: "t1",
                toolName: "shell",
                argsText: "",
                args: { command: "echo hi" },
                outputText,
                status: "done",
            }}
        />,
        { width: 90, height: 12 },
    );
    for (let pass = 0; pass < 3; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
    return setup.captureCharFrame();
}

test("tool output reaches the screen without terminal control sequences", async () => {
    const rendered = await frame("plain\n\x1b]52;c;AAAA\x07clipboard\n\x1b[2Jdone");
    expect(rendered).not.toContain("\x1b");
    expect(rendered).toContain("plain");
    expect(rendered).toContain("clipboard");
    expect(rendered).toContain("done");
    // the OSC payload must not leak into the frame
    expect(rendered).not.toContain("AAAA");
});

test("a carriage-return progress line shows only its final frame", async () => {
    const rendered = await frame("10%\r50%\r100%");
    expect(rendered).toContain("100%");
    expect(rendered).not.toContain("10%");
});
