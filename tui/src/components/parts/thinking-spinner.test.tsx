import { describe, expect, mock, test } from "bun:test";
import { mockedThemeModule } from "../../test-utils/mocked-theme.ts";

mock.module("../../context/theme.tsx", mockedThemeModule);

const { retrySuffix, ThinkingSpinner } = await import("./ThinkingSpinner.tsx");
const { useChatStore } = await import("../../stores/chat-store.ts");
const { testRender } = await import("@opentui/react/test-utils");
const { act } = await import("react");

describe("retrySuffix", () => {
    test("is empty while the model is only thinking", () => {
        expect(retrySuffix(null)).toBe("");
    });

    test("names the attempt, the wait and the upstream reason", () => {
        expect(
            retrySuffix({
                attempt: 1,
                total: 6,
                waitSeconds: 60,
                reason: "HTTP 429",
            }),
        ).toBe(" · retry 1/6 in 60s · HTTP 429");
    });

    test("omits the wait and the reason when the frame carries none", () => {
        expect(
            retrySuffix({ attempt: 2, total: 0, waitSeconds: 0, reason: "" }),
        ).toBe(" · retry 2");
    });

    test("passes the whole upstream reason through to be wrapped", () => {
        const reason = "quota is exhausted for this IP/account, upgrade or wait";
        expect(
            retrySuffix({
                attempt: 1,
                total: 6,
                waitSeconds: 5,
                reason: `  ${reason}  `,
            }),
        ).toBe(` · retry 1/6 in 5s · ${reason}`);
    });
});

describe("ThinkingSpinner", () => {
    test("shows the retry line while the provider is waiting", async () => {
        act(() =>
            useChatStore.getState().setRetry({
                attempt: 1,
                total: 6,
                waitSeconds: 60,
                reason: "HTTP 429",
            }),
        );
        const setup = await testRender(<ThinkingSpinner />, {
            width: 80,
            height: 5,
        });
        await setup.flush();
        const frame = setup.captureCharFrame();

        expect(frame).toContain("Thinking…");
        expect(frame).toContain("retry 1/6 in 60s");
        expect(frame).toContain("HTTP 429");

        act(() => useChatStore.getState().setRetry(null));
    });

    test("wraps a long reason instead of cutting it", async () => {
        act(() =>
            useChatStore.getState().setRetry({
                attempt: 1,
                total: 6,
                waitSeconds: 60,
                reason: "OpenCode Zen free-tier quota is exhausted for this IP/account, upgrade or wait.",
            }),
        );
        const setup = await testRender(<ThinkingSpinner />, {
            width: 60,
            height: 6,
        });
        await setup.flush();
        const frame = setup.captureCharFrame();

        expect(frame).toContain("quota is exhausted");
        expect(frame).toContain("upgrade or wait.");

        act(() => useChatStore.getState().setRetry(null));
    });

    test("has no retry text once the wait is over", async () => {
        act(() => useChatStore.getState().setRetry(null));
        const setup = await testRender(<ThinkingSpinner />, {
            width: 80,
            height: 5,
        });
        await setup.flush();

        expect(setup.captureCharFrame()).not.toContain("retry");
    });
});
