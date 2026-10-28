import { beforeEach, describe, expect, test } from "bun:test";
import { useChatStore, type TuiMessage } from "./chat-store.ts";

function messages(): TuiMessage[] {
    return useChatStore.getState().messages;
}

function assistantId(): string {
    const message = messages().find((item) => item.role === "assistant");
    if (!message) throw new Error("assistant message missing");
    return message.id;
}

beforeEach(() => {
    useChatStore.setState({
        messages: [],
        sessionId: null,
        isStreaming: false,
        provider: "",
        model: "",
        agentKey: "main",
        agentName: "Nova",
    });
});

describe("chat-store messages", () => {
    test("addUserMessage appends a completed user message", () => {
        useChatStore.getState().addUserMessage("hello");
        expect(messages()).toHaveLength(1);
        expect(messages()[0]?.role).toBe("user");
        expect(messages()[0]?.parts).toEqual([{ type: "text", text: "hello" }]);
        expect(messages()[0]?.status).toBe("done");
    });

    test("startAssistantMessage marks the stream and seeds a pending part", () => {
        const id = useChatStore.getState().startAssistantMessage();
        expect(useChatStore.getState().isStreaming).toBe(true);
        expect(messages()[0]?.status).toBe("streaming");
        expect(messages()[0]?.parts).toEqual([{ type: "pending" }]);
        expect(messages()[0]?.id).toBe(id);
    });

    test("completeStream finalises the message and drops pending parts", () => {
        useChatStore.getState().startAssistantMessage();
        useChatStore.getState().completeStream();
        expect(useChatStore.getState().isStreaming).toBe(false);
        expect(messages()[0]?.status).toBe("done");
        expect(messages()[0]?.parts).toEqual([]);
    });

    test("failStream carries the error", () => {
        useChatStore.getState().startAssistantMessage();
        useChatStore.getState().failStream("nope");
        expect(messages()[0]?.status).toBe("error");
        expect(messages()[0]?.error).toBe("nope");
    });

    test("a finished stream resolves a tool call it never answered", () => {
        // The backend can end a turn right after announcing a call (a refused
        // command used to send no result at all). Nothing arrives later to
        // clear the spinner, and isStreaming is false, so ESC cannot help.
        const id = useChatStore.getState().startAssistantMessage();
        useChatStore.getState().startToolCall(id, {
            toolCallId: "t1",
            toolName: "shell",
        });
        useChatStore.getState().completeStream();
        const part = messages()[0]?.parts[0];
        expect(part?.type === "tool-call" && part.status).toBe("error");
        expect(part?.type === "tool-call" && part.error).toBeTruthy();
    });

    test("a failed stream resolves its tool call too", () => {
        const id = useChatStore.getState().startAssistantMessage();
        useChatStore.getState().startToolCall(id, {
            toolCallId: "t1",
            toolName: "shell",
        });
        useChatStore.getState().failStream("connection lost");
        const part = messages()[0]?.parts[0];
        expect(part?.type === "tool-call" && part.status).toBe("error");
    });
});

describe("chat-store text and reasoning", () => {
    test("text deltas append to one part", () => {
        const id = useChatStore.getState().startAssistantMessage();
        useChatStore.getState().startTextPart(id);
        useChatStore.getState().appendTextDelta(id, "hel");
        useChatStore.getState().appendTextDelta(id, "lo");
        expect(messages()[0]?.parts).toEqual([
            { type: "text", text: "hello" },
        ]);
    });

    test("reasoning start/append/end", () => {
        const id = useChatStore.getState().startAssistantMessage();
        useChatStore.getState().startReasoningPart(id);
        useChatStore.getState().appendReasoningDelta(id, "why");
        useChatStore.getState().endReasoningPart(id, 42);
        expect(messages()[0]?.parts).toEqual([
            {
                type: "reasoning",
                text: "why",
                elapsedMs: 42,
                completed: true,
            },
        ]);
    });
});

describe("chat-store tool calls", () => {
    function startTool(): string {
        const id = useChatStore.getState().startAssistantMessage();
        useChatStore.getState().startToolCall(id, {
            toolCallId: "t1",
            toolName: "read",
        });
        return id;
    }

    test("startToolCall drops pending and empty text parts", () => {
        const id = useChatStore.getState().startAssistantMessage();
        useChatStore.getState().startTextPart(id);
        useChatStore.getState().appendTextDelta(id, "  ");
        useChatStore.getState().startToolCall(id, {
            toolCallId: "t1",
            toolName: "read",
        });
        expect(messages()[0]?.parts).toEqual([
            {
                type: "tool-call",
                toolCallId: "t1",
                toolName: "read",
                argsText: "",
                args: null,
                outputText: "",
                status: "running",
            },
        ]);
    });

    test("setToolInput keeps objects and stringifies everything else", () => {
        startTool();
        useChatStore.getState().setToolInput(assistantId(), "t1", {
            filePath: "x",
        });
        const part = messages()[0]?.parts[0];
        expect(part?.type).toBe("tool-call");
        if (part?.type !== "tool-call") return;
        expect(part.args).toEqual({ filePath: "x" });
        expect(part.argsText).toContain('"filePath"');
    });

    test("setToolOutput marks the call done", () => {
        startTool();
        useChatStore.getState().setToolOutput(assistantId(), "t1", "ok");
        const part = messages()[0]?.parts[0];
        expect(part?.type === "tool-call" && part.status).toBe("done");
        expect(part?.type === "tool-call" && part.outputText).toBe("ok");
    });

    test("setToolStatus and failToolCall update the matching call only", () => {
        startTool();
        useChatStore.getState().setToolStatus(assistantId(), "t1", "blocked");
        let part = messages()[0]?.parts[0];
        expect(part?.type === "tool-call" && part.status).toBe("blocked");

        useChatStore.getState().failToolCall(assistantId(), "t1", "bad");
        part = messages()[0]?.parts[0];
        expect(part?.type === "tool-call" && part.status).toBe("error");
        expect(part?.type === "tool-call" && part.error).toBe("bad");
    });
});

describe("chat-store wake messages", () => {
    test("deduplicates by wakeFor", () => {
        useChatStore.getState().insertWakeMessage("done", "job1");
        useChatStore.getState().insertWakeMessage("done", "job1");
        expect(messages()).toHaveLength(1);
    });

    test("stores the server variant on a wake message", () => {
        useChatStore.getState().insertWakeMessage("done", "job1", "subagent");
        expect(messages()[0]?.variant).toBe("subagent");
    });

    test("inserts above a streaming assistant message", () => {
        useChatStore.getState().startAssistantMessage();
        useChatStore.getState().insertWakeMessage("done", "job1");
        expect(messages().map((message) => message.role)).toEqual([
            "user",
            "assistant",
        ]);
    });
});

describe("chat-store reset", () => {
    test("clears messages and session state", () => {
        useChatStore.getState().addUserMessage("hi");
        useChatStore.getState().setSessionId("s1");
        useChatStore.getState().reset();
        expect(messages()).toEqual([]);
        expect(useChatStore.getState().sessionId).toBeNull();
        expect(useChatStore.getState().isStreaming).toBe(false);
    });
});
