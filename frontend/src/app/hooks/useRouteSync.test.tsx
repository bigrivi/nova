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

import { updateAgent } from "../../lib/nova-api";
import { useAgentRouteSync } from "./useRouteSync";

vi.mock("../../lib/nova-api", () => ({
    updateAgent: vi.fn().mockResolvedValue(undefined),
}));

const updateAgentMock = vi.mocked(updateAgent);

beforeEach(() => {
    updateAgentMock.mockClear();
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
