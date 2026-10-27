/** Rows for the searchable list: optional group headers plus selectable items. */

export type ListRow<T> =
    | { kind: "header"; label: string }
    | { kind: "spacer" }
    | { kind: "item"; item: T; index: number };

/**
 * Flatten items into rows, inserting a blank row and a header whenever the
 * group changes.
 *
 * Args:
 *   items: Filtered items, already contiguous by group (callers keep their
 *     order; this only detects boundaries).
 *   groupOf: Group label per item. Omit for a flat list with no headers.
 *
 * Returns:
 *   One row per item, plus one spacer and one header row at the start of each
 *   group except the first.
 */
export function buildRows<T>(
    items: T[],
    groupOf?: (item: T) => string | undefined,
): ListRow<T>[] {
    const rows: ListRow<T>[] = [];
    let current: string | undefined;
    items.forEach((item, index) => {
        const group = groupOf?.(item);
        if (group !== undefined && group !== current) {
            if (rows.length > 0) {
                rows.push({ kind: "spacer" });
            }
            rows.push({ kind: "header", label: group });
        }
        current = group;
        rows.push({ kind: "item", item, index });
    });
    return rows;
}

/** Row index of the row that selects item *index*, or -1 when absent. */
export function rowOf<T>(rows: ListRow<T>[], index: number): number {
    return rows.findIndex((row) => row.kind === "item" && row.index === index);
}
