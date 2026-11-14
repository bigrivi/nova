import { afterEach, expect, test } from "bun:test";

// No api mock here: `mock.module` is process wide, and a stubbed
// `listSessions` would reach the api tests that run later. The startup
// requests fail against a backend that is not there and are handled.

const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");
const { App } = await import("./App.tsx");
const { AppProvider } = await import("../context/app.tsx");
const { useApprovalStore } = await import("../stores/approval-store.ts");
const { useAskUserStore } = await import("../stores/ask-user-store.ts");
const { useChatStore } = await import("../stores/chat-store.ts");

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 4; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 30));
    }
}

async function render() {
    const setup = await testRender(
        <AppProvider>
            <App onExit={() => {}} />
        </AppProvider>,
        { width: 100, height: 24 },
    );
    await settle(setup);
    return setup;
}

const QUESTION = {
    id: "q1",
    header: "Pick one",
    question: "Which branch?",
    inputType: "text" as const,
    options: [],
    multiple: false,
    required: false,
};

const APPROVAL = {
    sessionId: "s1",
    requestId: "r1",
    command: "rm -rf build",
    description: "remove the build directory",
    toolName: "",
    rememberable: false,
    family: "",
    target: "build",
    scriptScoped: false,
    dangerous: false,
    workspace: "",
    runId: 0,
};

afterEach(() => {
    useAskUserStore.getState().setActive(null);
    useApprovalStore.getState().setPending(null);
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: "",
        model: "",
    });
});

// The rounded corner of the composer card: the question form and the approval
// dialog draw their own frames, so this is what says "the composer is up".
// The placeholder text is not a marker: it names the saved session count.
const COMPOSER = "╭";

test("a question replaces the composer and gives it back", async () => {
    const setup = await render();
    expect(setup.captureCharFrame()).toContain(COMPOSER);

    act(() => useAskUserStore.getState().setActive([QUESTION]));
    await settle(setup);
    const asking = setup.captureCharFrame();
    expect(asking).toContain("Which branch?");
    expect(asking).not.toContain(COMPOSER);

    act(() => useAskUserStore.getState().setActive(null));
    await settle(setup);
    expect(setup.captureCharFrame()).toContain(COMPOSER);
});

test("an approval replaces the composer and gives it back", async () => {
    const setup = await render();
    expect(setup.captureCharFrame()).toContain(COMPOSER);

    act(() => useApprovalStore.getState().setPending(APPROVAL));
    await settle(setup);
    const approving = setup.captureCharFrame();
    expect(approving).toContain("rm -rf build");
    expect(approving).not.toContain(COMPOSER);

    act(() => useApprovalStore.getState().setPending(null));
    await settle(setup);
    expect(setup.captureCharFrame()).toContain(COMPOSER);
});
