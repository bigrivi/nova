import type { ThreadMessageLike } from "@assistant-ui/react";

import i18n from "../i18n";
import type { NovaAttachmentData } from "../types/nova";
import { randomId } from "./utils";

/**
 * Build a plain text thread message for the given role, generating an id when
 * one is not supplied.
 */
export function createTextMessage(
    role: "user" | "assistant",
    text: string,
    id?: string,
): ThreadMessageLike {
    return {
        id: id ?? randomId(),
        role,
        content: text,
        createdAt: new Date(),
    };
}

/**
 * Combine prompt text with any image attachments into thread message content.
 * Returns the bare text when there are no images so simple messages stay
 * string-shaped.
 */
export function buildUserMessageParts(
    text: string,
    attachments?: NovaAttachmentData[],
): ThreadMessageLike["content"] {
    const imageParts: { type: "image"; image: string }[] = [];
    for (const attachment of attachments ?? []) {
        for (const part of attachment.content) {
            if (part.type === "image" && typeof part.image === "string") {
                imageParts.push({ type: "image", image: part.image });
            }
        }
    }
    if (imageParts.length === 0) {
        return text;
    }
    return [...imageParts, { type: "text", text }];
}

/**
 * Build an empty assistant message ready to receive streamed content parts.
 */
export function createAssistantMessage(id?: string): ThreadMessageLike {
    return {
        id: id ?? randomId(),
        role: "assistant",
        content: [],
        createdAt: new Date(),
    };
}

/**
 * Derive an optimistic session title from the first user message, truncating
 * long prompts and falling back to a localized default when empty.
 */
export function createOptimisticSessionTitle(userMessage: string): string {
    const title = userMessage.trim();
    if (!title) {
        return i18n.t("app.newSession");
    }

    if (title.length > 50) {
        return `${title.slice(0, 47)}...`;
    }

    return title;
}

/**
 * Strip the standalone welcome placeholder so the first real turn starts from
 * an empty draft thread; otherwise return the messages untouched.
 */
export function buildDraftMessages(previous: ThreadMessageLike[]) {
    if (
        previous.length === 1 &&
        previous[0]?.id === "welcome" &&
        previous[0]?.role === "assistant"
    ) {
        return [];
    }
    return previous;
}
