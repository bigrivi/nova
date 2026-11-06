import { beforeEach, describe, expect, test } from "bun:test";

import { chatSlice, emptySlice, useChat } from "./chat";

beforeEach(() => {
    useChat.setState({ byId: {} });
});

describe("chat slices", () => {
    test("text deltas merge into one part", () => {
        useChat.getState().appendUserMessage("tab_a", "hello");
        useChat.getState().startAssistant("tab_a");
        useChat.getState().appendText("tab_a", "Hel");
        useChat.getState().appendText("tab_a", "lo");

        const slice = chatSlice("tab_a");
        expect(slice.messages).toHaveLength(2);
        expect(slice.messages[1]!.parts).toEqual([
            { type: "text", text: "Hello" },
        ]);
        expect(slice.streaming).toBe(true);
    });

    test("reasoning and text are separate parts in arrival order", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().appendReasoning("tab_a", "think");
        useChat.getState().endReasoning("tab_a", 1200);
        useChat.getState().appendText("tab_a", "answer");

        expect(chatSlice("tab_a").messages[0]!.parts).toEqual([
            {
                type: "reasoning",
                text: "think",
                elapsedMs: 1200,
                completed: true,
            },
            { type: "text", text: "answer" },
        ]);
    });

    test("a tool is created once and updated by id", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().upsertTool("tab_a", {
            toolCallId: "t1",
            toolName: "read",
            inputText: '{"path":"a"}',
            status: "running",
        });
        useChat.getState().upsertTool("tab_a", {
            toolCallId: "t1",
            outputText: "contents",
            status: "done",
        });
        useChat.getState().upsertTool("tab_a", {
            toolCallId: "t2",
            toolName: "shell",
            status: "error",
            error: "denied",
        });

        const parts = chatSlice("tab_a").messages[0]!.parts;
        expect(parts).toHaveLength(2);
        expect(parts[0]).toMatchObject({
            type: "tool-call",
            toolCallId: "t1",
            outputText: "contents",
            status: "done",
        });
        expect(parts[1]).toMatchObject({
            type: "tool-call",
            toolCallId: "t2",
            status: "error",
            error: "denied",
        });
    });

    test("a retry line is cleared by finishing the turn", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().setRetry("tab_a", {
            attempt: 2,
            total: 6,
            waitSeconds: 4,
            reason: "endpoint unavailable",
        });
        expect(chatSlice("tab_a").messages[0]!.retry).toMatchObject({
            attempt: 2,
            total: 6,
        });
        useChat.getState().finishTurn("tab_a");
        expect(chatSlice("tab_a").messages[0]!.retry).toBeNull();
    });

    test("a new assistant starts without a stale retry line", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().setRetry("tab_a", {
            attempt: 1,
            total: 3,
            waitSeconds: 1,
            reason: "x",
        });
        useChat.getState().startAssistant("tab_a");
        const messages = chatSlice("tab_a").messages;
        expect(messages[messages.length - 1]!.retry).toBeNull();
    });

    test("finishing marks the assistant and clears streaming", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().appendText("tab_a", "done");
        useChat.getState().finishTurn("tab_a");

        const slice = chatSlice("tab_a");
        expect(slice.streaming).toBe(false);
        expect(slice.messages[0]!.status).toBe("done");
    });

    test("an error finishes the turn as failed", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().finishTurn("tab_a", "boom");

        const slice = chatSlice("tab_a");
        expect(slice.error).toBe("boom");
        expect(slice.messages[0]!.status).toBe("error");
        expect(slice.messages[0]!.error).toBe("boom");
    });

    test("history replaces a slice and clears transient state", () => {
        useChat.getState().setApproval("tab_a", {
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
        useChat.getState().loadHistory("tab_a", "s1", [
            {
                id: "m1",
                role: "assistant",
                parts: [{ type: "text", text: "old" }],
                status: "done",
            },
        ]);

        const slice = chatSlice("tab_a");
        expect(slice.sessionId).toBe("s1");
        expect(slice.messages).toHaveLength(1);
        expect(slice.approval).toBeNull();
        expect(slice.streaming).toBe(false);
    });

    test("a new assistant clears a pending question form", () => {
        useChat.getState().setAsk("tab_a", [
            {
                id: "q",
                header: "",
                question: "Why?",
                inputType: "text",
                options: [],
                multiple: false,
                required: true,
                default: "",
            },
        ]);
        useChat.getState().startAssistant("tab_a");
        expect(chatSlice("tab_a").ask).toBeNull();
    });

    test("history load keeps the agent and drops a stale question", () => {
        useChat.getState().setAgent("tab_a", "research");
        useChat.getState().setAsk("tab_a", []);
        useChat.getState().loadHistory("tab_a", "s1", []);
        expect(chatSlice("tab_a").agentKey).toBe("research");
        expect(chatSlice("tab_a").ask).toBeNull();
    });

    test("a user message keeps local attachment previews", () => {
        useChat.getState().appendUserMessage("tab_a", "", undefined, [
            { kind: "image", uri: "file:///a.jpg", name: "a.jpg" },
        ]);
        expect(chatSlice("tab_a").messages[0]!.attachments).toEqual([
            { kind: "image", uri: "file:///a.jpg", name: "a.jpg" },
        ]);
    });

    test("removing a tab drops only that slice", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().startAssistant("tab_b");
        useChat.getState().remove("tab_a");
        expect(chatSlice("tab_a")).toEqual(emptySlice());
        expect(chatSlice("tab_b").messages).toHaveLength(1);
    });
});

describe("session route state", () => {
    test("model and effort survive a history reload", () => {
        useChat.getState().setModel("tab_a", "opt_1");
        useChat.getState().setEffort("tab_a", "high");
        useChat.getState().loadHistory("tab_a", "ses_1", []);

        const slice = chatSlice("tab_a");
        expect(slice.modelId).toBe("opt_1");
        expect(slice.effort).toBe("high");
    });
});

describe("regenerate helpers", () => {
    test("drops only the final assistant message", () => {
        useChat.getState().appendUserMessage("tab_a", "hello");
        useChat.getState().startAssistant("tab_a");
        useChat.getState().appendText("tab_a", "answer");
        useChat.getState().finishTurn("tab_a");
        useChat.getState().appendUserMessage("tab_a", "next");
        useChat.getState().startAssistant("tab_a");
        useChat.getState().appendText("tab_a", "second answer");
        useChat.getState().finishTurn("tab_a");

        useChat.getState().dropLastAssistant("tab_a");

        const messages = chatSlice("tab_a").messages;
        expect(messages.map((m) => m.role)).toEqual([
            "user",
            "assistant",
            "user",
        ]);
        expect(messages[1]!.parts).toEqual([
            { type: "text", text: "answer" },
        ]);
    });

    test("streaming can start before a placeholder exists", () => {
        useChat.getState().setStreaming("tab_a", true);

        expect(chatSlice("tab_a").streaming).toBe(true);
        expect(chatSlice("tab_a").messages).toEqual([]);
    });
});

describe("turn teardown", () => {
    test("a tool still running when the turn ends becomes an error", () => {
        useChat.getState().startAssistant("tab_a");
        useChat.getState().upsertTool("tab_a", {
            toolCallId: "call_1",
            toolName: "shell",
            status: "running",
        });
        useChat.getState().finishTurn("tab_a", "Connection lost");

        const part = chatSlice("tab_a").messages[0]!.parts[0]!;
        expect(part.type).toBe("tool-call");
        if (part.type === "tool-call") {
            expect(part.status).toBe("error");
            expect(part.error).toContain("before this tool returned");
        }
    });
});
