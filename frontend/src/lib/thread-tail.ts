/**
 * Pure decision logic for tailing server-initiated turns.
 *
 * A sub-agent completion wakes the parent with a fresh turn after the
 * original SSE closed. The client learns about it through a session-state
 * `active` event and must open a resume stream — but only under the right
 * conditions:
 *
 * - background thread: ignore (lighting only; the thread resumes on open).
 * - own turn (a stream this client started itself, incl. its reattach):
 *   ignore — parking it would make our own cleanup fire a spurious empty
 *   resume.
 * - open thread, no local stream: tail immediately.
 * - open thread, local stream still draining: park the request; the draining
 *   stream's cleanup consumes it. Tailing now would race the open stream,
 *   and doing nothing would miss the turn entirely (no further event
 *   arrives for an already-active session).
 */
export type TailDecision = "tail-now" | "park" | "ignore";

export interface TailEventInput {
    /** Session-state active event (false for idle/teardown bookkeeping). */
    active: boolean;
    /** The event is for the currently open thread. */
    current: boolean;
    /** This client already has a local stream open on the thread. */
    localStream: boolean;
    /** The active event belongs to a stream this client started itself. */
    ownTurn: boolean;
}

export function decideTailOnActive(input: TailEventInput): TailDecision {
    if (!input.active || !input.current || input.ownTurn) {
        return "ignore";
    }
    return input.localStream ? "park" : "tail-now";
}

/**
 * Consume a parked tail request at local-stream cleanup.
 *
 * Always clears the flag; returns the thread id to tail, or null when there
 * is nothing parked (or the user has since switched away, in which case
 * opening the thread resumes it instead). The delete-then-check makes
 * consumption exactly-once.
 */
export function consumeParkedTail(
    parked: Set<string>,
    threadId: string,
    isCurrentThread: boolean,
): string | null {
    const wasParked = parked.delete(threadId);
    return wasParked && isCurrentThread ? threadId : null;
}
