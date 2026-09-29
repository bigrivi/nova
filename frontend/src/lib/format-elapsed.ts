/**
 * Elapsed-time readout for a voice take, as `mm:ss`.
 *
 * Rolls into `mm:ss` past an hour rather than wrapping, so a long take never
 * shows a smaller number than the one before it.
 */
export function formatElapsed(startedAt: number, now: number): string {
    const totalSeconds = Math.max(0, Math.floor((now - startedAt) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${pad(minutes)}:${pad(seconds)}`;
}

function pad(value: number): string {
    return String(value).padStart(2, "0");
}
