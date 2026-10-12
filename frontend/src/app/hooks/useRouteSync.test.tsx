// @vitest-environment jsdom
//
// The two route writers, tested against the failures their comments describe.
//
// Both are one-line-guard-plus-one-write effects, and both guards exist because
// something once went wrong: a restore echoing back out and overwriting the
// agent's defaults, and a draft's cleared route leaking into the conversation
// opened after it. A guard with no test is a comment, and a comment stops being
// read.

import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionRoute, updateAgent } from "../../lib/nova-api";
import { useAgentRouteSync, useSessionRouteSync } from "./useRouteSync";

vi.mock("../../lib/nova-api", () => ({
    updateAgent: vi.fn().mockResolvedValue(undefined),
    setSessionRoute: vi.fn().mockResolvedValue(undefined),
}));

const updateAgentMock = vi.mocked(updateAgent);
const setSessionRouteMock = vi.mocked(setSessionRoute);

beforeEach(() => {
    updateAgentMock.mockClear();
    setSessionRouteMock.mockClear();
});

const AGENT_DEFAULTS = {
    agentKey: "main",
    selectedModelId: "openai:gpt-4",
    reasoningEffort: null,
};

describe("useAgentRouteSync", () => {
    it("pushes an explicit pick to the agent", () => {
        // The agent row is the default a brand-new conversation starts from, so
        // a pick has to reach it or the next conversation silently uses the old
        // model.
        renderHook(() => useAgentRouteSync(AGENT_DEFAULTS));

        expect(updateAgentMock).toHaveBeenCalledTimes(1);
        expect(updateAgentMock).toHaveBeenCalledWith("main", {
            provider: "openai",
            model: "gpt-4",
            reasoningEffort: null,
        });
    });

    it("carries the reasoning level, which means nothing beside another model", () => {
        renderHook(() =>
            useAgentRouteSync({ ...AGENT_DEFAULTS, reasoningEffort: "high" }),
        );

        expect(updateAgentMock.mock.calls[0][1].reasoningEffort).toBe("high");
    });

    it("pushes nothing when no model is selected", () => {
        // Half the population has no provider configured yet. A push with an
        // empty route would overwrite a working default.
        renderHook(() =>
            useAgentRouteSync({ ...AGENT_DEFAULTS, selectedModelId: null }),
        );

        expect(updateAgentMock).not.toHaveBeenCalled();
    });

    it("does not push the same pick twice", () => {
        // Re-rendering is not a change. Without this the component writes on
        // every parent render, which is the whole cost of a ref guard.
        const { rerender } = renderHook(() => useAgentRouteSync(AGENT_DEFAULTS));

        rerender();
        rerender();

        expect(updateAgentMock).toHaveBeenCalledTimes(1);
    });

    it("a restored route does not push to the agent", () => {
        // Reopening a conversation writes its route back into the UI, and those
        // writes travel out through here. Left alone, reopening a conversation
        // whose route matches the agent's current default would push that
        // default back over the conversation's own record.
        //
        // The model has to *change* for this to be observable: the suppression is
        // read by the push effect, so a restore that moved nothing would also
        // push nothing and prove nothing.
        const { result, rerender } = renderHook(
            ({ model }: { model: string }) =>
                useAgentRouteSync({ ...AGENT_DEFAULTS, selectedModelId: model }),
            { initialProps: { model: "openai:gpt-4" } },
        );
        updateAgentMock.mockClear();

        result.current.beginRestore();
        rerender({ model: "anthropic:sonnet" });

        expect(updateAgentMock).not.toHaveBeenCalled();
    });

    it("the next genuine change after a restore does push", () => {
        // The flag is consumed by one skip, not cleared on a timer. If the next
        // real pick were swallowed as well, model changes would silently stop
        // reaching the agent after any conversation was reopened.
        const { result, rerender } = renderHook(
            ({ model }: { model: string }) =>
                useAgentRouteSync({ ...AGENT_DEFAULTS, selectedModelId: model }),
            { initialProps: { model: "openai:gpt-4" } },
        );
        updateAgentMock.mockClear();

        result.current.beginRestore();
        rerender({ model: "anthropic:sonnet" });
        expect(updateAgentMock).not.toHaveBeenCalled();

        rerender({ model: "openai:gpt-4" });

        expect(updateAgentMock).toHaveBeenCalledTimes(1);
        expect(updateAgentMock.mock.calls[0][1]).toMatchObject({
            provider: "openai",
            model: "gpt-4",
        });
    });

    it("changing the model without a restore does push", () => {
        // The control for the two above: without it, a test that asserted "no
        // push" would also pass against a hook that never pushed at all.
        const { rerender } = renderHook(
            ({ model }: { model: string }) =>
                useAgentRouteSync({ ...AGENT_DEFAULTS, selectedModelId: model }),
            { initialProps: { model: "openai:gpt-4" } },
        );
        updateAgentMock.mockClear();

        rerender({ model: "anthropic:sonnet" });

        expect(updateAgentMock).toHaveBeenCalledTimes(1);
        expect(updateAgentMock).toHaveBeenCalledWith("main", {
            provider: "anthropic",
            model: "sonnet",
            reasoningEffort: null,
        });
    });
});

describe("useSessionRouteSync", () => {
    const OPEN = {
        selectedModelId: "openai:gpt-4",
        reasoningEffort: null,
        isNewChat: false,
        threadId: "thread-1",
    };

    it("records the route on the conversation on screen", () => {
        renderHook(() => useSessionRouteSync(OPEN));

        expect(setSessionRouteMock).toHaveBeenCalledWith("thread-1", {
            provider: "openai",
            model: "gpt-4",
            reasoning_effort: null,
        });
    });

    it("sends reasoning_effort in snake_case, unlike the agent writer", () => {
        // Two different endpoints. `reasoningEffort` here is a silently ignored
        // field: the request succeeds, the level is not stored, and nothing
        // reports an error.
        renderHook(() =>
            useSessionRouteSync({ ...OPEN, reasoningEffort: "high" }),
        );

        expect(setSessionRouteMock.mock.calls[0][1]).toHaveProperty(
            "reasoning_effort",
            "high",
        );
        expect(setSessionRouteMock.mock.calls[0][1]).not.toHaveProperty(
            "reasoningEffort",
        );
    });

    it("records nothing while drafting", () => {
        // A draft has no session to record against; inventing one would write a
        // route to a conversation that does not exist.
        renderHook(() => useSessionRouteSync({ ...OPEN, isNewChat: true }));

        expect(setSessionRouteMock).not.toHaveBeenCalled();
    });

    it("does not push the same route to the same conversation twice", () => {
        const { rerender } = renderHook(() => useSessionRouteSync(OPEN));

        rerender();
        rerender();

        expect(setSessionRouteMock).toHaveBeenCalledTimes(1);
    });

    it("records again when another conversation is opened at the same model", () => {
        // The conversation is part of this key precisely so switching threads
        // re-pushes. Without it, opening a conversation that ran on something
        // else leaves its record saying otherwise.
        const { rerender } = renderHook(
            ({ threadId }: { threadId: string | null }) =>
                useSessionRouteSync({ ...OPEN, threadId }),
            { initialProps: { threadId: "thread-1" as string | null } },
        );

        rerender({ threadId: "thread-2" });

        expect(setSessionRouteMock).toHaveBeenCalledTimes(2);
        expect(setSessionRouteMock.mock.calls[1][0]).toBe("thread-2");
    });

    it("records again after returning from a draft", () => {
        // A conversation opened after a draft has its own record, so the cleared
        // draft key must not suppress its first write.
        const { rerender } = renderHook(
            ({ isNewChat }: { isNewChat: boolean }) =>
                useSessionRouteSync({ ...OPEN, isNewChat }),
            { initialProps: { isNewChat: false } },
        );
        setSessionRouteMock.mockClear();

        rerender({ isNewChat: true });
        expect(setSessionRouteMock).not.toHaveBeenCalled();
        rerender({ isNewChat: false });

        expect(setSessionRouteMock).toHaveBeenCalledTimes(1);
    });
});