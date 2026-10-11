import type { ThreadMessageLike } from "@assistant-ui/react";
import { beforeEach, describe, expect, it } from "vitest";

import { DRAFT_THREAD_ID } from "../lib/nova-constants";
import type { NovaThreadSummary } from "../types/nova";
import {
    selectActiveThreadListId,
    selectCurrentMessages,
    selectIsRunning,
    useConversationStore,
    type ConversationState,
} from "./conversation-store";

function thread(id: string): NovaThreadSummary {
    return {
        id,
        title: id,
        status: "regular",
        workspace_dir: null,
        pinned: false,
        updated_at: 0,
        project_id: null,
        agent_key: "main",
    };
}

function message(text: string): ThreadMessageLike {
    return { role: "user", content: text };
}

beforeEach(() => {
    useConversationStore.setState({
        threads: [],
        messagesByThreadId: { [DRAFT_THREAD_ID]: [] },
        currentThreadId: DRAFT_THREAD_ID,
        draftProjectId: null,
        runningByThread: {},
    });
});

describe("conversation-store actions", () => {
    it("starts with an empty draft thread selected", () => {
        const state = useConversationStore.getState();
        expect(state.currentThreadId).toBe(DRAFT_THREAD_ID);
        expect(state.messagesByThreadId).toEqual({ [DRAFT_THREAD_ID]: [] });
        expect(state.threads).toEqual([]);
        expect(state.runningByThread).toEqual({});
    });

    it("setThreads accepts a value and an updater", () => {
        useConversationStore.getState().setThreads([thread("a")]);
        expect(useConversationStore.getState().threads).toEqual([thread("a")]);

        useConversationStore
            .getState()
            .setThreads((previous) => [...previous, thread("b")]);
        expect(
            useConversationStore.getState().threads.map((t) => t.id),
        ).toEqual(["a", "b"]);
    });

    it("setThreadMessages creates a buffer for a new thread", () => {
        useConversationStore.getState().setThreadMessages("t1", [message("hi")]);
        expect(useConversationStore.getState().messagesByThreadId.t1).toEqual([
            message("hi"),
        ]);
    });

    it("setThreadMessages applies a function updater against the current buffer", () => {
        useConversationStore.getState().setThreadMessages("t1", [message("a")]);
        useConversationStore
            .getState()
            .setThreadMessages("t1", (previous) => [
                ...previous,
                message("b"),
            ]);
        expect(
            (useConversationStore.getState().messagesByThreadId.t1 ?? []).map(
                (m) => m.content,
            ),
        ).toEqual(["a", "b"]);
    });

    it("setThreadMessages leaves other threads untouched", () => {
        useConversationStore.getState().setThreadMessages("t1", [message("a")]);
        useConversationStore.getState().setThreadMessages("t2", [message("b")]);
        const { messagesByThreadId } = useConversationStore.getState();
        expect(messagesByThreadId.t1).toEqual([message("a")]);
        expect(messagesByThreadId.t2).toEqual([message("b")]);
        expect(messagesByThreadId[DRAFT_THREAD_ID]).toEqual([]);
    });

    it("setMessagesByThreadId accepts a value and an updater", () => {
        useConversationStore
            .getState()
            .setMessagesByThreadId({ x: [message("a")] });
        expect(useConversationStore.getState().messagesByThreadId).toEqual({
            x: [message("a")],
        });
        useConversationStore
            .getState()
            .setMessagesByThreadId((previous) => ({ ...previous, y: [] }));
        expect(
            Object.keys(useConversationStore.getState().messagesByThreadId),
        ).toEqual(["x", "y"]);
    });

    it("setCurrentThreadId and setDraftProjectId update selection", () => {
        useConversationStore.getState().setCurrentThreadId("t9");
        useConversationStore.getState().setDraftProjectId("p1");
        expect(useConversationStore.getState().currentThreadId).toBe("t9");
        expect(useConversationStore.getState().draftProjectId).toBe("p1");
    });

    it("setRunningByThread accepts a value and an updater", () => {
        useConversationStore.getState().setRunningByThread({ a: true });
        expect(useConversationStore.getState().runningByThread).toEqual({
            a: true,
        });
        useConversationStore
            .getState()
            .setRunningByThread((previous) => ({ ...previous, b: true }));
        expect(useConversationStore.getState().runningByThread).toEqual({
            a: true,
            b: true,
        });
    });

    it("setThreadRunning turns a thread on and removes it when off", () => {
        useConversationStore.getState().setThreadRunning("t1", true);
        expect(useConversationStore.getState().runningByThread).toEqual({
            t1: true,
        });
        useConversationStore.getState().setThreadRunning("t1", false);
        expect(useConversationStore.getState().runningByThread).toEqual({});
    });
});

describe("conversation-store selectors", () => {
    const base: ConversationState = useConversationStore.getState();

    it("selectIsRunning reflects the current thread's flag only", () => {
        expect(
            selectIsRunning({
                ...base,
                currentThreadId: "t1",
                runningByThread: { t1: true },
            }),
        ).toBe(true);
        expect(
            selectIsRunning({
                ...base,
                currentThreadId: "t1",
                runningByThread: { t2: true },
            }),
        ).toBe(false);
    });

    it("selectCurrentMessages falls back to an empty list", () => {
        expect(
            selectCurrentMessages({
                ...base,
                currentThreadId: "missing",
                messagesByThreadId: {},
            }),
        ).toEqual([]);
        expect(
            selectCurrentMessages({
                ...base,
                currentThreadId: "t1",
                messagesByThreadId: { t1: [message("hi")] },
            }),
        ).toEqual([message("hi")]);
    });

    it("selectActiveThreadListId is defined only for a listed thread", () => {
        expect(
            selectActiveThreadListId({
                ...base,
                currentThreadId: "t1",
                threads: [thread("t1")],
            }),
        ).toBe("t1");
        expect(
            selectActiveThreadListId({
                ...base,
                currentThreadId: DRAFT_THREAD_ID,
                threads: [thread("t1")],
            }),
        ).toBeUndefined();
    });
});
