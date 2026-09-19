import type { ThreadMessageLike } from "@assistant-ui/react";
import { describe, expect, it, vi } from "vitest";

import type { NovaStreamEvent } from "../types/nova";
import {
    handleStreamEvent,
    STREAM_PATCH_TYPES,
    type StreamEngineDeps,
    type StreamHandlerEnv,
} from "./stream-engine";
import { DRAFT_THREAD_ID } from "./nova-constants";

function makeEnv(overrides: Partial<StreamHandlerEnv> = {}): StreamHandlerEnv {
    return {
        originThreadId: "t-1",
        prompt: "hello",
        draftProjectId: null,
        agentKey: "main",
        assistantMessageId: "a-1",
        state: { activeThreadId: "t-1" },
        flags: { requiresInput: false, pendingAskUser: null },
        ...overrides,
    };
}

function makeDeps(overrides: Partial<StreamEngineDeps> = {}): StreamEngineDeps {
    return {
        abortControllersRef: { current: new Map() },
        seenSequencesRef: { current: new Map() },
        sessionIdRef: { current: "t-1" },
        currentThreadIdRef: { current: "t-1" },
        setThreadRunning: vi.fn(),
        setThreadMessages: vi.fn(),
        setMessagesByThreadId: vi.fn(),
        setCurrentThreadId: vi.fn(),
        setThreads: vi.fn(),
        runTransition: (fn) => fn(),
        reasoning: { setCompacting: vi.fn() },
        approval: { setPendingForSession: vi.fn(), setPending: vi.fn() },
        todo: { setActive: vi.fn() },
        ...overrides,
    };
}

describe("handleStreamEvent sequence dedup", () => {
    it("skips a replayed sequence for the same thread", () => {
        const deps = makeDeps();
        const env = makeEnv();
        const event: NovaStreamEvent = {
            type: "text-delta",
            delta: "x",
            sequence: 7,
        };
        handleStreamEvent(event, env, deps);
        handleStreamEvent(event, env, deps);
        expect(deps.setThreadMessages).toHaveBeenCalledTimes(1);
        expect(deps.seenSequencesRef.current.get("t-1")?.has(7)).toBe(true);
    });

    it("applies unsequenced events every time", () => {
        const deps = makeDeps();
        const env = makeEnv();
        const event: NovaStreamEvent = { type: "text-delta", delta: "x" };
        handleStreamEvent(event, env, deps);
        handleStreamEvent(event, env, deps);
        expect(deps.setThreadMessages).toHaveBeenCalledTimes(2);
    });
});

describe("handleStreamEvent control frames", () => {
    it("toggles compaction on start and end", () => {
        const deps = makeDeps();
        const env = makeEnv();
        handleStreamEvent({ type: "data-nova-compaction-start" }, env, deps);
        expect(deps.reasoning.setCompacting).toHaveBeenLastCalledWith(true);
        handleStreamEvent({ type: "data-nova-compaction-end" }, env, deps);
        expect(deps.reasoning.setCompacting).toHaveBeenLastCalledWith(false);
    });

    it("ignores heartbeat frames", () => {
        const deps = makeDeps();
        handleStreamEvent({ type: "data-nova-heartbeat" }, makeEnv(), deps);
        expect(deps.setThreadMessages).not.toHaveBeenCalled();
        expect(deps.reasoning.setCompacting).not.toHaveBeenCalled();
    });

    it("sets pending approval only for the current thread", () => {
        const deps = makeDeps({ currentThreadIdRef: { current: "t-1" } });
        const event: NovaStreamEvent = {
            type: "data-nova-approval-required",
            data: { requestId: "r", command: "c", description: "d" },
        };
        handleStreamEvent(event, makeEnv(), deps);
        expect(deps.approval.setPendingForSession).toHaveBeenCalledWith("t-1", {
            sessionId: "t-1",
            requestId: "r",
            command: "c",
            description: "d",
        });
        expect(deps.approval.setPending).toHaveBeenCalledTimes(1);
    });

    it("does not surface approval for a background thread", () => {
        const deps = makeDeps({ currentThreadIdRef: { current: "other" } });
        const event: NovaStreamEvent = {
            type: "data-nova-approval-required",
            data: { requestId: "r", command: "c", description: "d" },
        };
        handleStreamEvent(event, makeEnv(), deps);
        expect(deps.approval.setPendingForSession).toHaveBeenCalledTimes(1);
        expect(deps.approval.setPending).not.toHaveBeenCalled();
    });

    it("raises the requiresInput flag", () => {
        const env = makeEnv();
        handleStreamEvent({ type: "data-nova-input-required" }, env, makeDeps());
        expect(env.flags.requiresInput).toBe(true);
    });

    it("throws on error events", () => {
        expect(() =>
            handleStreamEvent(
                { type: "error", errorText: "boom" },
                makeEnv(),
                makeDeps(),
            ),
        ).toThrow("boom");
    });
});

describe("handleStreamEvent tool side effects", () => {
    it("captures ask-user input and still patches the message", () => {
        const deps = makeDeps();
        const env = makeEnv();
        handleStreamEvent(
            {
                type: "tool-input-available",
                toolCallId: "call-1",
                toolName: "ask_user",
                input: { q: 1 },
            },
            env,
            deps,
        );
        expect(env.flags.pendingAskUser).toEqual({ input: { q: 1 } });
        expect(deps.todo.setActive).not.toHaveBeenCalled();
        expect(deps.setThreadMessages).toHaveBeenCalledTimes(1);
    });

    it("routes todo_write input to the todo store", () => {
        const deps = makeDeps();
        handleStreamEvent(
            {
                type: "tool-input-available",
                toolCallId: "call-2",
                toolName: "todo_write",
                input: { todos: [] },
            },
            makeEnv(),
            deps,
        );
        expect(deps.todo.setActive).toHaveBeenCalledWith({ todos: [] });
    });
});

describe("handleStreamEvent patch dispatch", () => {
    it("patches every STREAM_PATCH_TYPES event onto the active thread", () => {
        for (const type of STREAM_PATCH_TYPES) {
            const deps = makeDeps();
            handleStreamEvent(
                { type, toolCallId: "c", data: { toolCallId: "c" } } as NovaStreamEvent,
                makeEnv(),
                deps,
            );
            expect(deps.setThreadMessages).toHaveBeenCalledWith(
                "t-1",
                expect.any(Function),
            );
        }
    });
});

describe("handleStreamEvent session handoff", () => {
    it("migrates controller, sequences, running flags and takes over the view", () => {
        const controller = new AbortController();
        const seen = new Set<number>([1, 2]);
        const deps = makeDeps({
            abortControllersRef: { current: new Map([["t-1", controller]]) },
            seenSequencesRef: { current: new Map([["t-1", seen]]) },
            sessionIdRef: { current: "t-1" },
        });
        const env = makeEnv({ state: { activeThreadId: "t-1" } });

        handleStreamEvent(
            { type: "data-nova-session", data: { sessionId: "real-1" } },
            env,
            deps,
        );

        expect(env.state.activeThreadId).toBe("real-1");
        expect(deps.abortControllersRef.current.get("real-1")).toBe(controller);
        expect(deps.abortControllersRef.current.has("t-1")).toBe(false);
        expect(deps.seenSequencesRef.current.get("real-1")).toBe(seen);
        expect(deps.setThreadRunning).toHaveBeenCalledWith("t-1", false);
        expect(deps.setThreadRunning).toHaveBeenCalledWith("real-1", true);
        expect(deps.setCurrentThreadId).toHaveBeenCalledWith("real-1");
        expect(deps.sessionIdRef.current).toBe("real-1");
        expect(deps.setThreads).toHaveBeenCalledTimes(1);
    });

    it("does not take over the view when the user moved to another thread", () => {
        const deps = makeDeps({ sessionIdRef: { current: "other" } });
        const env = makeEnv({ state: { activeThreadId: "t-1" } });
        handleStreamEvent(
            { type: "data-nova-session", data: { sessionId: "real-1" } },
            env,
            deps,
        );
        expect(deps.setCurrentThreadId).not.toHaveBeenCalled();
        expect(deps.sessionIdRef.current).toBe("other");
    });

    it("clears draft messages when handing off from the draft thread", () => {
        const deps = makeDeps({ sessionIdRef: { current: DRAFT_THREAD_ID } });
        let stored: Record<string, ThreadMessageLike[]> = {
            [DRAFT_THREAD_ID]: [
                { id: "u", role: "user", content: "hi", createdAt: new Date(0) },
            ],
        };
        (deps.setMessagesByThreadId as ReturnType<typeof vi.fn>).mockImplementation(
            (updater: (p: Record<string, ThreadMessageLike[]>) => Record<string, ThreadMessageLike[]>) => {
                stored = updater(stored);
            },
        );
        const env = makeEnv({ state: { activeThreadId: DRAFT_THREAD_ID } });

        handleStreamEvent(
            { type: "data-nova-session", data: { sessionId: "real-1" } },
            env,
            deps,
        );

        expect(stored[DRAFT_THREAD_ID]).toEqual([]);
        expect(stored["real-1"]).toHaveLength(1);
    });

    it("drops the optimistic draft entry when handing off from the draft thread", () => {
        const deps = makeDeps({ sessionIdRef: { current: DRAFT_THREAD_ID } });
        let storedThreads = [
            {
                id: DRAFT_THREAD_ID,
                title: "optimistic",
                status: "regular",
                workspace_dir: null,
                project_id: null,
                pinned: false,
                updated_at: 0,
                agent_key: "main",
            },
        ];
        (
            deps.setThreads as ReturnType<typeof vi.fn>
        ).mockImplementation(
            (
                updater: (
                    p: typeof storedThreads,
                ) => typeof storedThreads,
            ) => {
                storedThreads = updater(storedThreads);
            },
        );
        const env = makeEnv({ state: { activeThreadId: DRAFT_THREAD_ID } });

        handleStreamEvent(
            { type: "data-nova-session", data: { sessionId: "real-1" } },
            env,
            deps,
        );

        expect(
            storedThreads.some((t) => t.id === DRAFT_THREAD_ID),
        ).toBe(false);
        expect(storedThreads.some((t) => t.id === "real-1")).toBe(true);
    });

    it("ignores a handoff to the same or empty session id", () => {
        const deps = makeDeps();
        const env = makeEnv({ state: { activeThreadId: "t-1" } });
        handleStreamEvent(
            { type: "data-nova-session", data: { sessionId: "t-1" } },
            env,
            deps,
        );
        handleStreamEvent(
            { type: "data-nova-session", data: {} },
            env,
            deps,
        );
        expect(deps.setThreads).not.toHaveBeenCalled();
        expect(deps.setThreadRunning).not.toHaveBeenCalled();
    });
});
