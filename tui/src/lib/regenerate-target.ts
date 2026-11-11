/** Where a regenerated answer goes in the transcript.
 *
 *  The server re-runs the last user message and drops the answer that followed
 *  it, so the client has to decide what to replace:
 *
 *  - the transcript ends with an assistant answer: that answer is replaced, and
 *    the new one streams into the same bubble;
 *  - the transcript ends with a user message: there is no answer yet, so a new
 *    assistant bubble is appended;
 *  - there is no user message at all: there is nothing to regenerate.
 *
 *  Pure on purpose: this is the decision that would otherwise be wrong in a way
 *  nobody notices until the wrong bubble disappears.
 */
import type { TuiMessage } from "../stores/chat-store.ts";

export type RegenerateTarget =
    | { kind: "replace"; messageId: string }
    | { kind: "append" }
    | { kind: "none"; reason: string };

export function regenerateTarget(messages: TuiMessage[]): RegenerateTarget {
    // The server re-runs a *user* message, so a transcript without one has
    // nothing to regenerate -- the same 400 it would answer with.
    if (!messages.some((message) => message.role === "user")) {
        return {
            kind: "none",
            reason: "This conversation has no user message to answer again.",
        };
    }
    const last = messages[messages.length - 1];
    if (!last) {
        return { kind: "none", reason: "This conversation has nothing to regenerate yet." };
    }
    if (last.role === "assistant") {
        return { kind: "replace", messageId: last.id };
    }
    return { kind: "append" };
}
