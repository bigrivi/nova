import type { ThreadMessageLike } from "@assistant-ui/react";
import { describe, expect, it, vi } from "vitest";

import type { NovaStreamEvent } from "../types/nova";
import {
    handleStreamEvent,
    type StreamEngineDeps,
    type StreamHandlerEnv,
} from "./stream-engine";

const WAKE_TEXT = "[subagent:coder status=done]\ntask_id — background task id.";

function makeEnv(): StreamHandlerEnv {
    return {
        originThreadId: "t-1",
        prompt: "hello",
        draftProjectId: null,
        agentKey: "main",
        assistantMessageId: "a-1",
        state: { activeThreadId: "t-1" },
        flags: { requiresInput: false, pendingAskUser: null },
    };
}

/** Wire setThreadMessages to a real array so the updater actually runs. */
function makeDepsWithStore(initial: ThreadMessageLike[] = []) {
    let stored = initial;
    const setThreadMessages = vi.fn(
        (
            _threadId: string,
            updater:
                | ThreadMessageLike[]
                | ((messages: ThreadMessageLike[]) => ThreadMessageLike[]),
        ) => {
            stored =
                typeof updater === "function"
                    ? updater(stored)
                    : (updater as ThreadMessageLike[]);
        },
    );
    const deps = {
        abortControllersRef: { current: new Map() },
        seenSequencesRef: { current: new Map() },
        expectOwnActiveRef: { current: new Set<string>() },
        sessionIdRef: { current: "t-1" },
        currentThreadIdRef: { current: "t-1" },
        setThreadRunning: vi.fn(),
        setThreadMessages,
        setMessagesByThreadId: vi.fn(),
        setCurrentThreadId: vi.fn(),
        setThreads: vi.fn(),
        runTransition: (fn: () => void) => fn(),
        reasoning: {
            setCompacting: vi.fn(),
            appendCompactionDelta: vi.fn(),
        },
        approval: {
            setPendingForSession: vi.fn(),
            setPending: vi.fn(),
            clearPendingForSession: vi.fn(),
        },
        todo: { setActive: vi.fn() },
        contextUsage: { setForSession: vi.fn() },
    } satisfies StreamEngineDeps;
    return { deps, read: () => stored };
}

function wakeEvent(
    data: Record<string, unknown> = {},
    messageId = "msg_turn1",
): NovaStreamEvent {
    return {
        type: "data-nova-wake",
        data: { variant: "subagent", text: WAKE_TEXT, messageId, ...data },
    };
}

describe("data-nova-wake", () => {
    it("inserts the injected message with the variant the renderer keys on", () => {
        const { deps, read } = makeDepsWithStore();

        handleStreamEvent(wakeEvent(), makeEnv(), deps);

        expect(read()).toHaveLength(1);
        const [message] = read();
        expect(message.role).toBe("user");
        expect(message.content).toBe(WAKE_TEXT);
        expect(
            (message.metadata as { custom: { variant: string } }).custom
                .variant,
        ).toBe("subagent");
    });

    it("sits above the assistant reply, not below it", () => {
        // resumeThreadStream seeds the assistant message before it reads a
        // single frame, so a plain append drops the chip under the reply.
        const { deps, read } = makeDepsWithStore([
            {
                id: "u-1",
                role: "user",
                content: "delegate this",
                createdAt: new Date(0),
            },
            {
                id: "a-1",
                role: "assistant",
                content: [],
                createdAt: new Date(0),
            },
        ]);

        handleStreamEvent(wakeEvent(), makeEnv(), deps);

        expect(read().map((m) => m.role)).toEqual([
            "user",
            "user",
            "assistant",
        ]);
        expect(read()[1].content).toBe(WAKE_TEXT);
        expect(read()[2].id).toBe("a-1");
    });

    it("appends when the turn has no assistant message yet", () => {
        const { deps, read } = makeDepsWithStore([
            {
                id: "u-1",
                role: "user",
                content: "delegate this",
                createdAt: new Date(0),
            },
        ]);

        handleStreamEvent(wakeEvent(), makeEnv(), deps);

        expect(read().map((m) => m.role)).toEqual(["user", "user"]);
    });

    it("does not add a second chip when a replay redelivers the same frame", () => {
        // A resume from cursor 0 replays the frame; the turn it belongs to is
        // already inserted.
        const { deps, read } = makeDepsWithStore([
            {
                id: "already",
                role: "user",
                content: WAKE_TEXT,
                createdAt: new Date(0),
                metadata: {
                    custom: { variant: "subagent", wakeFor: "msg_turn1" },
                },
            },
        ]);

        handleStreamEvent(wakeEvent(), makeEnv(), deps);

        expect(read()).toHaveLength(1);
    });

    it("renders two identical reports from two separate runs", () => {
        // Two sub-agent runs that fail the same way produce byte-identical
        // text. Keyed on content, the second was silently dropped.
        const { deps, read } = makeDepsWithStore();

        handleStreamEvent(wakeEvent({}, "msg_turn1"), makeEnv(), deps);
        handleStreamEvent(wakeEvent({}, "msg_turn2"), makeEnv(), deps);

        expect(read()).toHaveLength(2);
        expect(read().every((m) => m.content === WAKE_TEXT)).toBe(true);
    });

    it("ignores a frame with no text", () => {
        const { deps, read } = makeDepsWithStore();

        handleStreamEvent(wakeEvent({ text: "" }), makeEnv(), deps);

        expect(read()).toHaveLength(0);
    });

    it("ignores a frame with no variant", () => {
        const { deps, read } = makeDepsWithStore();

        handleStreamEvent(wakeEvent({ variant: undefined }), makeEnv(), deps);

        expect(read()).toHaveLength(0);
    });

    it("ignores a frame with no message id", () => {
        // Half-identified is worse than none: without the per-turn id there is
        // no way to tell a replay from a genuine repeat.
        const { deps, read } = makeDepsWithStore();

        handleStreamEvent(wakeEvent({ messageId: undefined }), makeEnv(), deps);

        expect(read()).toHaveLength(0);
    });

    it("consumes the frame without touching the assistant message", () => {
        const { deps } = makeDepsWithStore();

        handleStreamEvent(wakeEvent(), makeEnv(), deps);

        // setThreadMessages ran once, for the insertion. A patch frame would
        // also route through it, so assert the updater added rather than patched.
        expect(deps.setThreadMessages).toHaveBeenCalledTimes(1);
    });
});
