/** Horizontal tab-strip layout, ported from opencode's adaptiveSessionTabLayout.
 *
 *  The active tab is never narrower than its neighbours: with room to spare the
 *  strip shares evenly and gives the leftover cells to the active tab, and under
 *  pressure the active tab holds its preferred width while the rest share what is
 *  left, down to a readable minimum. When the strip cannot show every tab, a
 *  sticky window of tabs is rendered between `‹N` and `N›` overflow markers.
 */

export const TAB_MIN_WIDTH = 8;
export const TAB_WIDTH = 22;
export const TAB_MAX_WIDTH = 32;
export const TAB_ADD_WIDTH = 3;
/** Fixed column budget for the status glyph: one lead, the glyph, one gap. */
export const TAB_STATUS_WIDTH = 3;

/** `‹12 ` and ` 12›` reserve one gap cell beside the digits. */
export function tabOverflowWidth(count: number): number {
    return String(count).length + 2;
}

export type TabLayoutItem = { id: string };

export type TabLayout<T extends TabLayoutItem> = {
    visible: T[];
    widths: number[];
    before: number;
    after: number;
    start: number;
    total: number;
};

export function adaptiveTabLayout<T extends TabLayoutItem>(
    tabs: readonly T[],
    activeId: string | null,
    available: number,
    previousStart = 0,
): TabLayout<T> {
    if (tabs.length === 0) {
        return {
            visible: [],
            widths: [],
            before: 0,
            after: 0,
            start: 0,
            total: 0,
        };
    }

    const activeIndex = tabs.findIndex((tab) => tab.id === activeId);
    const fit = (width: number) =>
        Math.min(
            tabs.length,
            Math.max(
                1,
                activeIndex === -1
                    ? Math.floor(Math.max(0, width) / TAB_MIN_WIDTH)
                    : 1 +
                          Math.floor(
                              (Math.max(0, width) - TAB_WIDTH) / TAB_MIN_WIDTH,
                          ),
            ),
        );

    const solve = (
        count: number,
        start: number,
        attempts: number,
    ): { count: number; start: number } => {
        const boundedStart = Math.min(
            Math.max(0, start),
            tabs.length - count,
        );
        const nextStart = Math.min(
            Math.max(
                0,
                activeIndex === -1
                    ? boundedStart
                    : activeIndex < boundedStart
                      ? activeIndex
                      : activeIndex >= boundedStart + count
                        ? activeIndex - count + 1
                        : boundedStart,
            ),
            tabs.length - count,
        );
        const markers =
            (nextStart > 0 ? tabOverflowWidth(nextStart) : 0) +
            (nextStart + count < tabs.length
                ? tabOverflowWidth(tabs.length - nextStart - count)
                : 0);
        const nextCount = fit(available - markers);
        if (nextCount === count || attempts === 0) {
            return { count, start: nextStart };
        }
        return solve(nextCount, nextStart, attempts - 1);
    };

    const solved = solve(fit(available), previousStart, 3);
    const visible = tabs.slice(solved.start, solved.start + solved.count);
    const before = solved.start;
    const after = tabs.length - solved.start - solved.count;
    const contentWidth = Math.max(
        1,
        available -
            (before > 0 ? tabOverflowWidth(before) : 0) -
            (after > 0 ? tabOverflowWidth(after) : 0),
    );
    const roomy = contentWidth >= TAB_WIDTH * visible.length;
    const total = roomy
        ? Math.min(contentWidth, TAB_MAX_WIDTH * visible.length)
        : contentWidth;

    if (roomy || activeIndex === -1) {
        const lead =
            activeIndex === -1 ? 0 : Math.max(0, activeIndex - solved.start);
        const width = Math.floor(total / visible.length);
        const remainder = total - width * visible.length;
        // Spare cells go to the active tab first: handing them out by position
        // made the selected tab the narrowest of the strip.
        const offset = (index: number) =>
            (index - lead + visible.length) % visible.length;
        return {
            visible,
            widths: visible.map(
                (_, index) => width + Number(offset(index) < remainder),
            ),
            before,
            after,
            start: solved.start,
            total,
        };
    }

    if (visible.length === 1) {
        return {
            visible,
            widths: [total],
            before,
            after,
            start: solved.start,
            total,
        };
    }

    const activeSlot = visible.findIndex((tab) => tab.id === activeId);
    const inactiveWidth = Math.min(
        TAB_WIDTH,
        Math.max(
            TAB_MIN_WIDTH,
            Math.floor((total - TAB_WIDTH) / (visible.length - 1)),
        ),
    );
    // Capping the active tab keeps the strip monotone: uncapped it swallowed
    // every leftover column, so it grew widest right where the roomy path
    // drops the emphasis. The cells the cap frees go back to the inactive tabs.
    const activeWidth = Math.min(
        TAB_WIDTH,
        total - inactiveWidth * (visible.length - 1),
    );
    const spare = total - activeWidth - inactiveWidth * (visible.length - 1);

    return {
        visible,
        widths: visible.map((tab, index) =>
            tab.id === activeId
                ? activeWidth
                : inactiveWidth +
                  Number((index < activeSlot ? index : index - 1) < spare),
        ),
        before,
        after,
        start: solved.start,
        total,
    };
}
