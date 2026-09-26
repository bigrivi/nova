/**
 * Reveal speed is held constant across every title. The animation crosses a
 * distance that grows with the text, so a fixed duration would make long
 * titles travel several times faster than short ones; scaling the duration by
 * the overflow keeps the perceived pace identical.
 */
export const REVEAL_VELOCITY_PX_PER_SECOND = 60;
const REVEAL_MIN_DURATION_SECONDS = 0.9;

/**
 * Scale a title's reveal duration by the distance it must travel, so every
 * title moves at the same speed instead of long ones racing past.
 *
 * Short overflows are slowed to a floor so they do not blink; from there on the
 * pace stays constant, however far the title has to travel.
 *
 * @param overflowPx Distance the text must travel, in pixels
 * @returns Animation duration in seconds, or 0 when nothing overflows
 */
export function revealDurationSeconds(overflowPx: number): number {
    if (overflowPx <= 0) {
        return 0;
    }
    return Math.max(
        REVEAL_MIN_DURATION_SECONDS,
        overflowPx / REVEAL_VELOCITY_PX_PER_SECOND,
    )
}
