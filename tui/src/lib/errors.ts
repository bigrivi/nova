/** Error reporting helpers shared by the shell.
 *
 *  A failure the user cannot act on (a backend that is not up yet, a model
 *  list that will not load) must not take the UI down, but it must not vanish
 *  either: a swallowed error is the reason a broken startup looks like a
 *  working one.
 */

/** The message of an unknown error value. */
export function errorText(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
}

/** Report a failure that is not worth interrupting the user for. */
export function logWarn(context: string, err: unknown): void {
    console.warn(`[nova] ${context}: ${errorText(err)}`);
}
