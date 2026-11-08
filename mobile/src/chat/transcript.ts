/** Plain-text transcript for sharing, copied from the rendered messages. */
import type { ChatMessage } from "../state/chat";

/**
 * Render the conversation as `You:` / `Nova:` blocks.
 *
 * Only text parts are included: reasoning, tool calls and attachments have no
 * meaning outside the app. Messages with no text (a tool-only turn) are skipped
 * so the output has no empty headers.
 *
 * @param messages Messages in display order.
 * @returns Blocks separated by a blank line.
 */
export function transcriptText(messages: readonly ChatMessage[]): string {
    return messages
        .map((message) => {
            const text = message.parts
                .filter((part) => part.type === "text")
                .map((part) => (part.type === "text" ? part.text : ""))
                .join("\n")
                .trim();
            if (!text) {
                return "";
            }
            const author = message.role === "user" ? "You" : "Nova";
            return `${author}:\n${text}`;
        })
        .filter(Boolean)
        .join("\n\n");
}
