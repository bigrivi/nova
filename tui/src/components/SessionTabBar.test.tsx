import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";

import { mockedThemeModule } from "../test-utils/mocked-theme.ts";

// Process-wide mock: the tab strip only needs a palette, not the app context.
mock.module("../context/theme.tsx", mockedThemeModule);

const { testRender } = await import("@opentui/react/test-utils");
const { MouseButtons } = await import("@opentui/core/testing");
const { act } = await import("react");
const { SessionTabBar } = await import("./SessionTabBar.tsx");
const { useChatStore } = await import("../stores/chat-store.ts");
const { useTabStore } = await import("../stores/tab-store.ts");
const { darkTheme } = await import("../themes/index.ts");

function rgbOf(hex: string): number[] {
    return [1, 3, 5].map((offset) =>
        Number.parseInt(hex.slice(offset, offset + 2), 16),
    );
}

type SpanLines = {
    lines: {
        spans: { text: string; fg: { buffer: ArrayLike<number> } }[];
    }[];
};

function spanAt(spans: SpanLines, text: string) {
    return spans.lines[0]!.spans.find((span) => span.text.trim() === text);
}

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

async function settle(setup: { flush: () => Promise<void> }): Promise<void> {
    for (let pass = 0; pass < 6; pass += 1) {
        await setup.flush();
        await new Promise((resolve) => setTimeout(resolve, 20));
    }
}

async function render() {
    const setup = await testRender(<SessionTabBar />, {
        width: 60,
        height: 3,
        enableMouseMovement: true,
    });
    await settle(setup);
    return setup;
}

function seed(): { first: string; second: string } {
    const first = useTabStore.getState().create({
        sessionId: "s1",
        title: "First",
    });
    const second = useTabStore.getState().create({
        sessionId: "s2",
        title: "Second",
    });
    useTabStore.getState().select(first.id);
    return { first: first.id, second: second.id };
}

beforeEach(() => {
    useTabStore.getState().reset();
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        retry: null,
        byId: {},
    });
});

afterEach(() => {
    // Both stores are process-wide; a leftover tab or streaming message would
    // leak into the next test file that renders App.
    useTabStore.getState().reset();
    useChatStore.getState().reset();
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        retry: null,
        byId: {},
    });
});

describe("session tab bar", () => {
    test("renders every tab title and keeps the status cell stable", async () => {
        seed();
        const setup = await render();
        try {
            const frame = setup.captureCharFrame();
            expect(frame).toContain("First");
            expect(frame).toContain("Second");
        } finally {
            setup.renderer.destroy();
        }
    });

    test("shows a close glyph on hover and closes that tab", async () => {
        const { first, second } = seed();
        const setup = await render();
        try {
            await act(async () => {
                await setup.mockMouse.moveTo(2, 0);
            });
            await setup.waitForFrame((frame) => frame.includes("✕"));
            const frame = setup.captureCharFrame();
            expect(frame).toContain("✕");
            const closeColumn = frame.split("\n")[0]!.indexOf("✕");
            expect(closeColumn).toBeGreaterThan(0);

            // Click the cell the glyph is actually painted in.
            await act(async () => {
                await setup.mockMouse.click(closeColumn, 0);
            });
            await settle(setup);

            expect(useTabStore.getState().tabs.map((tab) => tab.id)).toEqual([
                second,
            ]);
            expect(useTabStore.getState().activeId).toBe(second);
            expect(first).not.toBe(second);
        } finally {
            setup.renderer.destroy();
        }
    });

    test("middle click closes a tab without selecting it", async () => {
        const { first, second } = seed();
        const setup = await render();
        try {
            await act(async () => {
                await setup.mockMouse.click(32, 0, MouseButtons.MIDDLE);
            });
            await settle(setup);

            expect(useTabStore.getState().tabs.map((tab) => tab.id)).toEqual([
                first,
            ]);
            expect(useTabStore.getState().activeId).toBe(first);
            expect(second).not.toBe(first);
        } finally {
            setup.renderer.destroy();
        }
    });

    test("renders the unread marker on a background tab and clears it on select", async () => {
        const { first, second } = seed();
        useTabStore.getState().markTurnEnded(second, true);
        const setup = await render();
        try {
            expect(setup.captureCharFrame()).toContain("•");

            await act(async () => {
                await setup.mockMouse.click(35, 0);
            });
            await settle(setup);

            expect(useTabStore.getState().activeId).toBe(second);
            expect(
                useTabStore.getState().tabs.find((tab) => tab.id === second)
                    ?.unread,
            ).toBeNull();
            expect(first).not.toBe(second);
        } finally {
            setup.renderer.destroy();
        }
    });

    test("each state transition repaints the status cell in order", async () => {
        const { second } = seed(); // first is active; second is the background tab
        const setup = await render();
        const columns = new Set<number>();

        const capture = async () => {
            await settle(setup);
            const row = setup.captureCharFrame().split("\n")[0] ?? "";
            const titleColumn = row.indexOf("Second");
            expect(titleColumn).toBeGreaterThan(0);
            columns.add(titleColumn);

            const cell = row
                .slice(Math.max(0, titleColumn - 3), titleColumn)
                .trim();
            const glyph =
                cell === ""
                    ? ""
                    : SPINNER_FRAMES.includes(cell)
                      ? "spinner"
                      : cell;
            let color: number[] | null = null;
            if (cell !== "") {
                const span = spanAt(setup.captureSpans() as SpanLines, cell);
                expect(span).toBeDefined();
                color = Array.from(span!.fg.buffer).slice(0, 3);
            }
            return { glyph, color };
        };

        try {
            const observed = [await capture()]; // idle

            act(() => useTabStore.getState().setAttention(second, "approval"));
            observed.push(await capture());

            act(() => useTabStore.getState().setAttention(second, "question"));
            observed.push(await capture());

            act(() => {
                useTabStore.getState().setAttention(second, null);
                useChatStore.getState().startAssistantMessage(second);
            });
            observed.push(await capture());

            act(() => {
                useChatStore.getState().completeStream(second);
                useTabStore.getState().markTurnEnded(second, true);
            });
            observed.push(await capture());

            act(() => {
                useTabStore.getState().clearUnread(second);
                useTabStore.getState().markTurnEnded(second, false);
            });
            observed.push(await capture());

            // attention beats busy and unread
            act(() => {
                useTabStore.getState().setAttention(second, "approval");
                useChatStore.getState().startAssistantMessage(second);
            });
            observed.push(await capture());

            // busy beats unread
            act(() => useTabStore.getState().setAttention(second, null));
            observed.push(await capture());

            // idle again
            act(() => {
                useChatStore.getState().completeStream(second);
                useTabStore.getState().clearUnread(second);
            });
            observed.push(await capture());

            // idle → ! → ? → spinner → activity → error → ! → spinner → idle
            expect(observed.map((item) => item.glyph)).toEqual([
                "",
                "!",
                "?",
                "spinner",
                "•",
                "•",
                "!",
                "spinner",
                "",
            ]);
            expect(observed.map((item) => item.color)).toEqual([
                null,
                rgbOf(darkTheme.feedback.running),
                rgbOf(darkTheme.feedback.running),
                rgbOf(darkTheme.feedback.running),
                rgbOf(darkTheme.primary.base),
                rgbOf(darkTheme.feedback.error),
                rgbOf(darkTheme.feedback.running),
                rgbOf(darkTheme.feedback.running),
                null,
            ]);

            // Every transition changes either the glyph or its colour, and the
            // fixed status cell never pushes the title sideways.
            for (let index = 1; index < observed.length; index += 1) {
                expect(observed[index]).not.toEqual(observed[index - 1]);
            }
            expect(columns.size).toBe(1);
        } finally {
            setup.renderer.destroy();
        }
    });
});
