import type { ThreadMessageLike } from "@assistant-ui/react";
import { describe, expect, it } from "vitest";

import type { NovaAttachmentData } from "../types/nova";
import {
    buildDraftMessages,
    buildUserMessageParts,
    createAssistantMessage,
    createOptimisticSessionTitle,
    createTextMessage,
} from "./thread-messages";

function imageAttachment(image: string): NovaAttachmentData {
    return {
        content: [{ type: "image", image }],
    } as unknown as NovaAttachmentData;
}

describe("createTextMessage", () => {
    it("uses the supplied id and stores text content", () => {
        const message = createTextMessage("user", "hello", "id-1");
        expect(message.id).toBe("id-1");
        expect(message.role).toBe("user");
        expect(message.content).toBe("hello");
        expect(message.createdAt).toBeInstanceOf(Date);
    });

    it("generates an id when omitted", () => {
        const message = createTextMessage("assistant", "hi");
        expect(message.id).toBeTruthy();
    });
});

describe("buildUserMessageParts", () => {
    it("returns bare text when there are no attachments", () => {
        expect(buildUserMessageParts("hello")).toBe("hello");
    });

    it("returns bare text when attachments carry no images", () => {
        const attachment = {
            content: [{ type: "text", text: "doc" }],
        } as unknown as NovaAttachmentData;
        expect(buildUserMessageParts("hello", [attachment])).toBe("hello");
    });

    it("prepends image parts before the text part", () => {
        const parts = buildUserMessageParts("caption", [
            imageAttachment("data:image/png;base64,AAA"),
            imageAttachment("data:image/png;base64,BBB"),
        ]);
        expect(parts).toEqual([
            { type: "image", image: "data:image/png;base64,AAA" },
            { type: "image", image: "data:image/png;base64,BBB" },
            { type: "text", text: "caption" },
        ]);
    });
});

describe("createAssistantMessage", () => {
    it("creates an empty assistant message", () => {
        const message = createAssistantMessage("a-1");
        expect(message.id).toBe("a-1");
        expect(message.role).toBe("assistant");
        expect(message.content).toEqual([]);
    });
});

describe("createOptimisticSessionTitle", () => {
    it("returns the trimmed prompt when short", () => {
        expect(createOptimisticSessionTitle("  build a thing  ")).toBe(
            "build a thing",
        );
    });

    it("truncates long prompts to 47 chars plus ellipsis", () => {
        const long = "a".repeat(80);
        const title = createOptimisticSessionTitle(long);
        expect(title).toBe(`${"a".repeat(47)}...`);
        expect(title).toHaveLength(50);
    });

    it("falls back to a non-empty default for blank prompts", () => {
        expect(createOptimisticSessionTitle("   ")).toBeTruthy();
    });
});

describe("buildDraftMessages", () => {
    it("clears a lone welcome placeholder", () => {
        const welcome: ThreadMessageLike[] = [
            { id: "welcome", role: "assistant", content: [], createdAt: new Date(0) },
        ];
        expect(buildDraftMessages(welcome)).toEqual([]);
    });

    it("keeps real messages untouched", () => {
        const messages: ThreadMessageLike[] = [
            { id: "u-1", role: "user", content: "hi", createdAt: new Date(0) },
        ];
        expect(buildDraftMessages(messages)).toBe(messages);
    });

    it("keeps a single non-welcome assistant message", () => {
        const messages: ThreadMessageLike[] = [
            { id: "a-1", role: "assistant", content: [], createdAt: new Date(0) },
        ];
        expect(buildDraftMessages(messages)).toBe(messages);
    });
});
