import type { NovaThreadSummary } from "@/types/nova";

export type ChatDateBucket = "today" | "yesterday" | "last7Days" | "older";

export type SidebarProject = {
    key: string;
    label: string;
    qualifier: string | null;
    latestActivity: number;
    threads: NovaThreadSummary[];
};

export type SidebarGroups = {
    pinned: NovaThreadSummary[];
    projects: SidebarProject[];
    chats: Record<ChatDateBucket, NovaThreadSummary[]>;
};

function projectLabel(path: string): string {
    const normalized = path.replace(/[\\/]+$/, "");
    return normalized.split(/[\\/]/).at(-1) || normalized;
}

function parentLabel(path: string): string | null {
    const normalized = path.replace(/[\\/]+$/, "");
    const pieces = normalized.split(/[\\/]/).filter(Boolean);
    return pieces.length > 1 ? pieces.at(-2) ?? null : null;
}

export function dateBucket(
    updatedAt: number,
    now = new Date(),
): ChatDateBucket {
    const currentStart = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
    ).getTime();
    const timestamp = new Date(updatedAt).getTime();
    const day = 86_400_000;
    if (timestamp >= currentStart) return "today";
    if (timestamp >= currentStart - day) return "yesterday";
    if (timestamp >= currentStart - day * 7) return "last7Days";
    return "older";
}

export function groupThreads(
    threads: readonly NovaThreadSummary[],
    now = new Date(),
): SidebarGroups {
    const pinned = threads.filter((thread) => thread.pinned);
    const projectMap = new Map<string, NovaThreadSummary[]>();
    const chats: SidebarGroups["chats"] = {
        today: [],
        yesterday: [],
        last7Days: [],
        older: [],
    };

    for (const thread of threads) {
        if (thread.pinned) continue;
        if (thread.workspace_dir) {
            const items = projectMap.get(thread.workspace_dir) ?? [];
            items.push(thread);
            projectMap.set(thread.workspace_dir, items);
            continue;
        }
        chats[dateBucket(thread.updated_at, now)].push(thread);
    }

    const duplicateLabels = new Set<string>();
    const labels = new Map<string, number>();
    for (const key of projectMap.keys()) {
        const label = projectLabel(key);
        const count = (labels.get(label) ?? 0) + 1;
        labels.set(label, count);
        if (count > 1) duplicateLabels.add(label);
    }

    const projects = [...projectMap.entries()]
        .map(([key, items]) => ({
            key,
            label: projectLabel(key),
            qualifier: duplicateLabels.has(projectLabel(key))
                ? parentLabel(key)
                : null,
            latestActivity: Math.max(...items.map((item) => item.updated_at)),
            threads: items,
        }))
        .sort((left, right) => right.latestActivity - left.latestActivity);

    return { pinned, projects, chats };
}

export function nextThreadAfterDelete(
    threads: readonly NovaThreadSummary[],
    deletedId: string,
): string | null {
    const index = threads.findIndex((thread) => thread.id === deletedId);
    if (index < 0) return null;
    return threads[index + 1]?.id ?? threads[index - 1]?.id ?? null;
}
