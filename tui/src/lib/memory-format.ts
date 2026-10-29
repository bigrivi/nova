/** Row text and grouping for the memory panel.
 *
 *  A memory is only useful if the user can tell what it applies to, so the scope
 *  leads every row and doubles as the group header.
 */
import type { NovaMemory } from "../api/types.ts";

export type MemoryRow = {
    id: string;
    label: string;
    /** Scope name, used as the group header. */
    group: string;
};

const SUMMARY_WIDTH = 70;

/** `user · preference · I prefer tabs` */
export function memoryLine(memory: NovaMemory): string {
    const summary = (memory.summary || memory.content || memory.key)
        .replace(/\s+/g, " ")
        .trim();
    const clipped =
        summary.length > SUMMARY_WIDTH
            ? `${summary.slice(0, SUMMARY_WIDTH - 1)}…`
            : summary;
    return `${memory.memory_type || "note"} · ${clipped}`;
}

/**
 * Rows grouped by scope, largest scope first.
 *
 * The list component only draws a header when the group label changes, so the
 * rows have to be contiguous per scope.
 */
export function arrangeMemories(memories: NovaMemory[]): MemoryRow[] {
    const counts = new Map<string, number>();
    for (const memory of memories) {
        counts.set(memory.scope, (counts.get(memory.scope) ?? 0) + 1);
    }
    const scopes = [...counts.keys()].sort(
        (left, right) =>
            (counts.get(right) ?? 0) - (counts.get(left) ?? 0) ||
            left.localeCompare(right),
    );

    const rows: MemoryRow[] = [];
    for (const scope of scopes) {
        for (const memory of memories) {
            if (memory.scope !== scope) continue;
            rows.push({
                id: memory.id,
                label: memoryLine(memory),
                group: `${scope} (${counts.get(scope)})`,
            });
        }
    }
    return rows;
}

/** The full text shown in the detail panel. */
export function memoryDetailLines(memory: NovaMemory): string[] {
    const lines = [
        `${memory.scope} · ${memory.memory_type} · key ${memory.key}`,
        "",
        memory.content || memory.summary || "(empty)",
    ];
    if (memory.tags.length > 0) {
        lines.push("", `tags: ${memory.tags.join(", ")}`);
    }
    if (memory.session_id) {
        lines.push(`session: ${memory.session_id}`);
    }
    return lines;
}
