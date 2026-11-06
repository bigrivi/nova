/** Title search for the sessions list. */
export type SearchableSession = { title?: string | null };

/**
 * Filter sessions whose title contains the query, ignoring case and padding.
 *
 * @param sessions Sessions in display order.
 * @param query Raw search box text; blank keeps everything.
 * @returns Matching sessions in the same order.
 */
export function filterSessionsByTitle<T extends SearchableSession>(
    sessions: readonly T[],
    query: string,
): T[] {
    const needle = query.trim().toLowerCase();
    if (!needle) {
        return [...sessions];
    }
    return sessions.filter((session) =>
        (session.title ?? "").toLowerCase().includes(needle),
    );
}
