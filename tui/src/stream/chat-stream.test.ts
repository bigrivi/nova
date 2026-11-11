import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { useChatStore } from "../stores/chat-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import {
    requestInterrupt,
    resetInterruptGuardForTest,
    runChatStream,
    setInterruptTransportForTest,
    setStreamTransportForTest,
} from "./chat-stream.ts";

let calls = 0;

beforeEach(() => {
    calls = 0;
    resetInterruptGuardForTest();
    setInterruptTransportForTest(null);
    useToastStore.setState({ message: null });
});

afterEach(() => {
    setInterruptTransportForTest(null);
    setStreamTransportForTest(null);
    useChatStore.setState({ sessionId: null, isStreaming: false });
});

function stubInterrupt(outcome: boolean | null): void {
    setInterruptTransportForTest(async () => {
        calls += 1;
        return outcome;
    });
}

function streamingAs(sessionId: string): void {
    useChatStore.setState({ sessionId, isStreaming: true });
}

describe("requestInterrupt", () => {
    test("two immediate calls produce one fetch", async () => {
        streamingAs("s1");
        stubInterrupt(true);
        await Promise.all([requestInterrupt(), requestInterrupt()]);
        expect(calls).toBe(1);
    });

    test("no-op when not streaming", async () => {
        stubInterrupt(true);
        await requestInterrupt();
        expect(calls).toBe(0);
    });

    test("false outcome toasts nothing-to-cancel", async () => {
        streamingAs("s1");
        stubInterrupt(false);
        await requestInterrupt();
        expect(calls).toBe(1);
        expect(useToastStore.getState().message).toContain("already ended");
    });

    test("null outcome toasts unreachable", async () => {
        streamingAs("s1");
        stubInterrupt(null);
        await requestInterrupt();
        expect(useToastStore.getState().message).toContain("Could not reach");
    });

    test("true outcome shows no toast", async () => {
        streamingAs("s1");
        stubInterrupt(true);
        await requestInterrupt();
        expect(useToastStore.getState().message).toBeNull();
    });
});

describe("runChatStream", () => {
    test("the request carries the attachments the composer attached", async () => {
        // The image is a chip in the composer and a data URL in the request. A
        // month of refactoring dropped the second half of that sentence, and the
        // model answered questions about pictures it had never been sent.
        const captured: { attachments?: unknown }[] = [];
        setStreamTransportForTest(async (options) => {
            captured.push(options);
        });

        const attachments = [
            {
                id: "tui-1",
                type: "image",
                name: "shot.png",
                contentType: "image/png",
                content: [{ type: "image", image: "data:image/png;base64,AAA" }],
            },
        ];

        await runChatStream({
            message: "what is this",
            attachments: attachments as never,
        });

        expect(captured.at(-1)?.attachments).toEqual(attachments);
    });
});
