import { beforeEach, describe, expect, test } from "bun:test";

import type { AskQuestion } from "../chat/ask";
import { progressSlice, useChatProgress } from "./chat-progress";

const question: AskQuestion = {
    id: "q",
    header: "",
    question: "Why?",
    inputType: "text",
    options: [],
    multiple: false,
    required: true,
    default: "",
};

beforeEach(() => {
    useChatProgress.setState({ byId: {} });
});

describe("chat progress", () => {
    test("an approval clears a pending input notice", () => {
        const store = useChatProgress.getState();
        store.setRequiresInput("tab_a", "waiting");
        store.setApproval("tab_a", {
            requestId: "r",
            command: "x",
            description: "",
            toolName: "shell",
            rememberable: true,
            family: "",
            target: "",
            scriptScoped: false,
            dangerous: false,
            workspace: "",
        });

        expect(progressSlice("tab_a").approval?.requestId).toBe("r");
        expect(progressSlice("tab_a").requiresInput).toBeNull();

        useChatProgress.getState().setApproval("tab_a", null);
        expect(progressSlice("tab_a").approval).toBeNull();
    });

    test("clearing the notice leaves the approval alone", () => {
        useChatProgress.getState().setAsk("tab_a", [question]);
        useChatProgress.getState().setRequiresInput("tab_a", "answer me");

        expect(progressSlice("tab_a").ask).toHaveLength(1);
        expect(progressSlice("tab_a").requiresInput).toBe("answer me");
    });

    test("a new turn resets every progress field for its tab", () => {
        useChatProgress.getState().setAsk("tab_a", [question]);
        useChatProgress.getState().setTodos("tab_a", [
            { content: "one", status: "pending" },
        ]);
        useChatProgress.getState().setCompacting("tab_a", true);

        useChatProgress.getState().resetFor("tab_a");

        expect(progressSlice("tab_a")).toEqual({
            approval: null,
            context: null,
            requiresInput: null,
            ask: null,
            todos: null,
            compacting: false,
            compactionSummary: "",
        });
    });

    test("compaction keeps its summary across the end frame", () => {
        useChatProgress.getState().setCompacting("tab_a", true);
        useChatProgress.getState().appendCompaction("tab_a", "Request: ");
        useChatProgress.getState().appendCompaction("tab_a", "fix the bug");
        useChatProgress.getState().setCompacting("tab_a", false);

        expect(progressSlice("tab_a").compacting).toBe(false);
        expect(progressSlice("tab_a").compactionSummary).toBe(
            "Request: fix the bug",
        );

        useChatProgress.getState().setCompacting("tab_a", true);
        expect(progressSlice("tab_a").compactionSummary).toBe("");
    });

    test("remove and reset drop progress per tab", () => {
        useChatProgress.getState().setTodos("tab_a", [
            { content: "one", status: "pending" },
        ]);
        useChatProgress.getState().remove("tab_a");
        expect(progressSlice("tab_a").todos).toBeNull();

        useChatProgress.getState().setTodos("tab_b", [
            { content: "two", status: "pending" },
        ]);
        useChatProgress.getState().reset();
        expect(progressSlice("tab_b").todos).toBeNull();
    });
});
