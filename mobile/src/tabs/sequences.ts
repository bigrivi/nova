/** Per-tab SSE resume cursors.
 *
 *  Cursors are written on every frame, so they deliberately live outside the
 *  reactive tab list: a streaming tab must not re-render the strip hundreds of
 *  times per turn. This mirrors `sequences` in
 *  `tui/src/stores/tab-store.ts`.
 *
 *  Frames from a tab that was closed mid-turn still arrive for a moment. The
 *  `openIds` guard on `set` keeps such a frame from recreating a cursor for a
 *  tab the strip no longer has.
 */
export class TabSequences {
    private readonly values = new Map<string, number>();

    get(tabId: string): number {
        return this.values.get(tabId) ?? 0;
    }

    set(
        tabId: string,
        sequence: number,
        openIds?: ReadonlySet<string>,
    ): void {
        if (openIds !== undefined && !openIds.has(tabId)) {
            return;
        }
        this.values.set(tabId, sequence);
    }

    drop(tabId: string): void {
        this.values.delete(tabId);
    }

    clear(): void {
        this.values.clear();
    }
}
