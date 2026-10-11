import type { NovaBackgroundTask } from "../types/nova";

/**
 * A decoded frame from the session events SSE stream. The stream multiplexes
 * four frame kinds over one connection: the connect-time `snapshot`, per-session
 * `state` deltas, background `task` updates, and `title` renames.
 */
export type SessionFrame =
    | { type: "snapshot"; active: string[]; tasks: NovaBackgroundTask[] }
    | { type: "state"; sessionId: string; state: string }
    | { type: "task"; task: NovaBackgroundTask }
    | { type: "title"; sessionId: string; title: string };

/**
 * Decode one SSE `data:` payload into a typed frame.
 *
 * Returns `null` for anything that cannot be acted on - malformed JSON, a
 * non-object body, an unknown `type`, or a known type missing its required
 * fields. Callers treat `null` as non-fatal and wait for the next frame to
 * correct state, which matches how the raw stream was handled inline before.
 *
 * @param data The raw `event.data` string from the EventSource message.
 * @returns The decoded frame, or `null` when the frame is not actionable.
 */
export function parseSessionFrame(data: string): SessionFrame | null {
    let payload: unknown;
    try {
        payload = JSON.parse(data);
    } catch {
        return null;
    }
    if (!payload || typeof payload !== "object") {
        return null;
    }
    const frame = payload as Record<string, unknown>;
    switch (frame.type) {
        case "snapshot":
            return {
                type: "snapshot",
                active: Array.isArray(frame.active)
                    ? (frame.active as string[])
                    : [],
                tasks: Array.isArray(frame.tasks)
                    ? (frame.tasks as NovaBackgroundTask[])
                    : [],
            };
        case "state":
            if (
                typeof frame.session_id !== "string" ||
                typeof frame.state !== "string"
            ) {
                return null;
            }
            return {
                type: "state",
                sessionId: frame.session_id,
                state: frame.state,
            };
        case "task":
            if (!frame.task || typeof frame.task !== "object") {
                return null;
            }
            return { type: "task", task: frame.task as NovaBackgroundTask };
        case "title":
            if (
                typeof frame.session_id !== "string" ||
                typeof frame.title !== "string"
            ) {
                return null;
            }
            return {
                type: "title",
                sessionId: frame.session_id,
                title: frame.title,
            };
        default:
            return null;
    }
}
