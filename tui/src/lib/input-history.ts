/** Prompt recall for the composer: what was typed, newest last.
 *
 *  Module-level rather than component state on purpose. Launching the app,
 *  opening a screen, or loading another session remounts the composer, and
 *  losing every prompt with it is the annoyance this exists to remove. Nothing
 *  is written to disk, so history dies with the process.
 */

const MAX_ENTRIES = 50;

const entries: string[] = [];
let cursor: number | null = null;
let draft = "";

/** Record a submitted prompt. Blank text and repeats of the last entry are dropped. */
export function rememberInput(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (entries.at(-1) !== trimmed) {
        entries.push(trimmed);
        if (entries.length > MAX_ENTRIES) entries.shift();
    }
    resetHistoryCursor();
}

/**
 * Step back one prompt.
 *
 * Returns the text to show, or null at the oldest entry (or with no history),
 * which tells the caller to leave the textarea alone.
 */
export function historyUp(current: string): string | null {
    if (entries.length === 0) return null;
    if (cursor === null) {
        draft = current;
        cursor = entries.length - 1;
    } else if (cursor > 0) {
        cursor -= 1;
    } else {
        return null;
    }
    return entries[cursor] ?? null;
}

/** Step forward one prompt, restoring what was being typed past the newest entry. */
export function historyDown(): string | null {
    if (cursor === null) return null;
    cursor += 1;
    if (cursor >= entries.length) {
        cursor = null;
        return draft;
    }
    return entries[cursor] ?? null;
}

/** Forget where the cursor was: the user started typing something new. */
export function resetHistoryCursor(): void {
    cursor = null;
    draft = "";
}

/** True while the composer text came from recall rather than typing. */
export function isNavigatingHistory(): boolean {
    return cursor !== null;
}

/** Drop every entry. Tests only; the app never clears history. */
export function clearInputHistory(): void {
    entries.length = 0;
    resetHistoryCursor();
}
