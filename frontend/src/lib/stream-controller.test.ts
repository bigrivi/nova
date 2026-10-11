import type { ThreadMessageLike } from "@assistant-ui/react";
import { describe, expect, it, vi } from "vitest";

import { DRAFT_THREAD_ID } from "./nova-constants";
import {
    createStreamController,
    type StreamControllerDeps,
    type StreamRoute,
} from "./stream-controller";

type StreamChatArgs = Parameters<
    StreamControllerDeps["api"]["streamChat"]
>[0];

interface HarnessOptions {
    currentThreadId?: string;
    sessionId?: string;
    draftProjectId?: string | null;
    running?: Record<string, boolean>;
    route?: Partial<StreamRoute>;
}

function makeHarness(options: HarnessOptions = {}) {
    const currentThreadIdRef = {
        current: options.currentThreadId ?? DRAFT_THREAD_ID,
    };
    const sessionIdRef = {
        current: options.sessionId ?? currentThreadIdRef.current,
    };
    const running: Record<string, boolean> = { ...(options.running ?? {}) };
    const messages: Record<string, ThreadMessageLike[]> = {};

    let pending:
        | { args: StreamChatArgs; resolve: () => void; reject: (e: unknown) => void }
        | null = null;

    const streamChat = vi.fn(
        (args: StreamChatArgs) =>
            new Promise<void>((resolve, reject) => {
                pending = { args, resolve, reject };
            }),
    );

    const route: StreamRoute = {
        provider: "openai",
        model: "gpt",
        agentKey: "main",
        reasoningEffort: null,
        ...options.route,
    };

    const setThreadRunning = vi.fn((threadId: string, value: boolean) => {
        running[threadId] = value;
    });
    const setThreadMessages = vi.fn(
        (
            threadId: string,
            updater:
                | ThreadMessageLike[]
                | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]),
        ) => {
            const current = messages[threadId] || [];
            messages[threadId] =
                typeof updater === "function" ? updater(current) : updater;
        },
    );
    const setThreads = vi.fn();
    const setCurrentThreadId = vi.fn((threadId: string) => {
        currentThreadIdRef.current = threadId;
    });

    const api = {
        streamChat,
        getLastSequence: vi.fn(() => null),
        setLastSequence: vi.fn(),
        clearLastSequence: vi.fn(),
        interruptChat: vi.fn(async () => undefined),
    } as unknown as StreamControllerDeps["api"];

    const askUser = {
        setActiveForSession: vi.fn(),
        setActive: vi.fn(),
        clearActiveForSession: vi.fn(),
    };

    const deps: StreamControllerDeps = {
        currentThreadIdRef,
        sessionIdRef,
        conversation: {
            getCurrentThreadId: () => currentThreadIdRef.current,
            getDraftProjectId: () => options.draftProjectId ?? null,
            isRunning: (threadId) => !!running[threadId],
            setThreadRunning,
            setThreadMessages,
            setMessagesByThreadId: vi.fn(),
            setCurrentThreadId,
            setThreads,
        },
        getRoute: vi.fn(() => route),
        api,
        runTransition: (fn) => fn(),
        composer: { clear: vi.fn(), focus: vi.fn() },
        todo: { clear: vi.fn(), markOpenCancelled: vi.fn(), setActive: vi.fn() },
        reasoning: { setCompacting: vi.fn(), appendCompactionDelta: vi.fn() },
        approval: {
            setPendingForSession: vi.fn(),
            setPending: vi.fn(),
            clearPendingForSession: vi.fn(),
        },
        contextUsage: { setForSession: vi.fn() },
        askUser,
    };

    const controller = createStreamController(deps);

    return {
        controller,
        deps,
        streamChat,
        setThreadRunning,
        setThreadMessages,
        setThreads,
        askUser,
        messages,
        running,
        currentThreadIdRef,
        emit: (event: Record<string, unknown>) => {
            (pending?.args.onEvent as (e: unknown) => void)?.(event);
        },
        finish: () => pending?.resolve(),
        fail: (error: unknown) => pending?.reject(error),
        lastArgs: () => pending?.args,
    };
}

describe("stream-controller submit", () => {
    it("ignores an empty prompt", async () => {
        const h = makeHarness();
        await h.controller.submit("");
        expect(h.streamChat).not.toHaveBeenCalled();
    });

    it("ignores a submit while the origin thread is already running", async () => {
        const h = makeHarness({ running: { [DRAFT_THREAD_ID]: true } });
        await h.controller.submit("hi");
        expect(h.streamChat).not.toHaveBeenCalled();
    });

    it("ignores a second submit while a local stream is open", async () => {
        const h = makeHarness();
        void h.controller.submit("first");
        void h.controller.submit("second");
        expect(h.streamChat).toHaveBeenCalledTimes(1);
    });

    it("seeds the draft turn and streams with the resolved route", async () => {
        const h = makeHarness({
            route: {
                provider: "anthropic",
                model: "claude",
                agentKey: "main",
                reasoningEffort: "high",
            },
        });
        void h.controller.submit("hello");

        expect(h.deps.composer.clear).toHaveBeenCalled();
        expect(h.deps.composer.focus).toHaveBeenCalled();
        expect(h.deps.todo.clear).toHaveBeenCalled();
        expect(h.deps.api.clearLastSequence).toHaveBeenCalledWith(
            DRAFT_THREAD_ID,
        );
        // The draft buffer gets a user message followed by the assistant stub.
        expect(h.messages[DRAFT_THREAD_ID]).toHaveLength(2);
        expect(h.messages[DRAFT_THREAD_ID][0].role).toBe("user");
        expect(h.messages[DRAFT_THREAD_ID][1].role).toBe("assistant");
        // An optimistic thread is listed while the real id is pending.
        expect(h.setThreads).toHaveBeenCalled();
        expect(h.running[DRAFT_THREAD_ID]).toBe(true);

        const args = h.lastArgs();
        expect(args?.message).toBe("hello");
        expect(args?.sessionId).toBeNull();
        expect(args?.provider).toBe("anthropic");
        expect(args?.model).toBe("claude");
        expect(args?.agentKey).toBe("main");
        expect(args?.reasoningEffort).toBe("high");
        expect(args?.resumeFromSequence).toBeNull();

        h.finish();
    });

    it("submits an existing session without an optimistic placeholder", async () => {
        const h = makeHarness({ currentThreadId: "s1", sessionId: "s1" });
        void h.controller.submit("again");
        const args = h.lastArgs();
        expect(args?.sessionId).toBe("s1");
        expect(h.setThreads).not.toHaveBeenCalled();
        h.finish();
    });

    it("clears the running flag and the local stream after the turn settles", async () => {
        const h = makeHarness();
        const done = h.controller.submit("hi");
        expect(h.controller.hasLocalStream(DRAFT_THREAD_ID)).toBe(true);
        h.finish();
        await done;
        expect(h.running[DRAFT_THREAD_ID]).toBe(false);
        expect(h.controller.hasLocalStream(DRAFT_THREAD_ID)).toBe(false);
    });

    it("writes a failure notice when the stream throws", async () => {
        const h = makeHarness();
        const done = h.controller.submit("hi");
        const seedCalls = h.setThreadMessages.mock.calls.length;
        h.fail(new Error("boom"));
        await done;
        // One more setThreadMessages call than the submit seed: the notice.
        expect(h.setThreadMessages.mock.calls.length).toBeGreaterThan(seedCalls);
        expect(h.running[DRAFT_THREAD_ID]).toBe(false);
    });

    it("does not write a notice when the stream is aborted", async () => {
        const h = makeHarness();
        const done = h.controller.submit("hi");
        const seedCalls = h.setThreadMessages.mock.calls.length;
        h.fail(Object.assign(new Error("stop"), { name: "AbortError" }));
        await done;
        expect(h.setThreadMessages.mock.calls.length).toBe(seedCalls);
        expect(h.running[DRAFT_THREAD_ID]).toBe(false);
    });
});

describe("stream-controller own-turn registry", () => {
    it("marks an own turn once and reports it consumed thereafter", async () => {
        const h = makeHarness();
        void h.controller.submit("hi");
        expect(h.controller.consumeOwnActive(DRAFT_THREAD_ID)).toBe(true);
        expect(h.controller.consumeOwnActive(DRAFT_THREAD_ID)).toBe(false);
        h.finish();
    });
});

describe("stream-controller resume", () => {
    it("skips when a local stream is already open on the thread", async () => {
        const h = makeHarness({ currentThreadId: "s1", sessionId: "s1" });
        void h.controller.resume("s1", 3);
        expect(h.streamChat).toHaveBeenCalledTimes(1);
        void h.controller.resume("s1", 4);
        expect(h.streamChat).toHaveBeenCalledTimes(1);
        h.finish();
    });

    it("seeds an assistant stub and tails from the given sequence", async () => {
        const h = makeHarness({ currentThreadId: "s2", sessionId: "s2" });
        void h.controller.resume("s2", 7);
        expect(h.messages.s2).toHaveLength(1);
        expect(h.messages.s2[0].role).toBe("assistant");
        const args = h.lastArgs();
        expect(args?.sessionId).toBe("s2");
        expect(args?.resumeFromSequence).toBe(7);
        h.finish();
    });

    it("defaults a null cursor to sequence zero", async () => {
        const h = makeHarness({ currentThreadId: "s3", sessionId: "s3" });
        void h.controller.resume("s3", null);
        expect(h.lastArgs()?.resumeFromSequence).toBe(0);
        h.finish();
    });
});

describe("stream-controller cancel", () => {
    it("aborts, clears ask-user, cancels todos, and interrupts a real session", async () => {
        const h = makeHarness({ currentThreadId: "s1", sessionId: "s1" });
        void h.controller.resume("s1", 0);
        expect(h.controller.hasLocalStream("s1")).toBe(true);

        await h.controller.cancel("s1");
        expect(h.askUser.clearActiveForSession).toHaveBeenCalledWith("s1");
        expect(h.askUser.setActive).toHaveBeenCalledWith(null);
        expect(h.deps.todo.markOpenCancelled).toHaveBeenCalled();
        expect(h.deps.api.interruptChat).toHaveBeenCalledWith("s1");
    });

    it("never interrupts the draft thread on the server", async () => {
        const h = makeHarness();
        await h.controller.cancel(DRAFT_THREAD_ID);
        expect(h.deps.api.interruptChat).not.toHaveBeenCalled();
    });
});

describe("stream-controller ask-user handoff", () => {
    it("surfaces the ask-user call and resumes by submitting the answer", async () => {
        const h = makeHarness({ currentThreadId: "s1", sessionId: "s1" });
        const done = h.controller.resume("s1", 0);
        h.emit({ type: "data-nova-input-required" });
        h.emit({
            type: "tool-input-available",
            toolCallId: "call-1",
            toolName: "ask_user",
            input: { q: 1 },
        });
        h.finish();
        await done;

        expect(h.askUser.setActiveForSession).toHaveBeenCalledTimes(1);
        const [sessionId, call] = h.askUser.setActiveForSession.mock.calls[0];
        expect(sessionId).toBe("s1");
        // The resume answer goes back through submit as a fresh turn.
        const streamCalls = h.streamChat.mock.calls.length;
        (call as { resume: (text: unknown) => void }).resume("my answer");
        expect(h.streamChat.mock.calls.length).toBe(streamCalls + 1);
        expect(h.askUser.clearActiveForSession).toHaveBeenCalledWith("s1");
    });
});

describe("stream-controller parked tail", () => {
    it("tails a parked session once the draining stream cleans up", async () => {
        const h = makeHarness({ currentThreadId: "s1", sessionId: "s1" });
        const done = h.controller.resume("s1", 0);
        h.controller.parkTail("s1");
        expect(h.streamChat).toHaveBeenCalledTimes(1);
        h.finish();
        await done;
        // Cleanup consumed the parked request and opened a second tail.
        expect(h.streamChat).toHaveBeenCalledTimes(2);
    });
});
