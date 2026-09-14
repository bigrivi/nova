import type { NovaProject, NovaThreadSummary } from "@/types/nova";

export type ChatDateBucket = "today" | "yesterday" | "last7Days" | "older";

export type SidebarProject = {
    id: string;
    name: string;
    path: string | null;
    qualifier: string | null;
    pinnedCount: number;
    latestActivity: number;
    threads: NovaThreadSummary[];
};

export type SidebarGroups = {
    pinned: NovaThreadSummary[];
    projects: SidebarProject[];
    chats: Record<ChatDateBucket, NovaThreadSummary[]>;
};

function parentLabel(path: string | null): string | null {
    if (!path) {
        return null;
    }
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
    projects: readonly NovaProject[],
    now = new Date(),
): SidebarGroups {
    const pinned = threads.filter((thread) => thread.pinned);
    const chats: SidebarGroups["chats"] = {
        today: [],
        yesterday: [],
        last7Days: [],
        older: [],
    };
    const knownIds = new Set(projects.map((project) => project.id));
    const threadsByProject = new Map<string, NovaThreadSummary[]>(
        projects.map((project) => [project.id, []]),
    );
    const pinnedByProject = new Map<string, number>();

    for (const thread of threads) {
        // Pinned chats are exclusive: they live in the Pinned section only, and
        // the project just remembers how many of its chats were pinned away.
        if (thread.pinned) {
            if (thread.project_id && knownIds.has(thread.project_id)) {
                pinnedByProject.set(
                    thread.project_id,
                    (pinnedByProject.get(thread.project_id) ?? 0) + 1,
                );
            }
            continue;
        }
        if (thread.project_id && knownIds.has(thread.project_id)) {
            threadsByProject.get(thread.project_id)?.push(thread);
            continue;
        }
        chats[dateBucket(thread.updated_at, now)].push(thread);
    }

    const nameCounts = new Map<string, number>();
    for (const project of projects) {
        nameCounts.set(project.name, (nameCounts.get(project.name) ?? 0) + 1);
    }

    // Every project is listed, including ones without sessions yet - that row is
    // where a new session gets created.
    const grouped = projects
        .map((project) => {
            const items = threadsByProject.get(project.id) ?? [];
            return {
                id: project.id,
                name: project.name,
                path: project.path,
                qualifier:
                    (nameCounts.get(project.name) ?? 0) > 1
                        ? parentLabel(project.path)
                        : null,
                pinnedCount: pinnedByProject.get(project.id) ?? 0,
                latestActivity: items.length
                    ? Math.max(...items.map((item) => item.updated_at))
                    : project.updated_at,
                threads: items,
            };
        })
        .sort((left, right) => right.latestActivity - left.latestActivity);

    return { pinned, projects: grouped, chats };
}

export const DATE_BUCKETS: ChatDateBucket[] = [
    "today",
    "yesterday",
    "last7Days",
    "older",
];

export function orderedThreads(groups: SidebarGroups): NovaThreadSummary[] {
    const seen = new Set<string>();
    const ordered: NovaThreadSummary[] = [];
    const push = (thread: NovaThreadSummary) => {
        if (seen.has(thread.id)) return;
        seen.add(thread.id);
        ordered.push(thread);
    };

    groups.pinned.forEach(push);
    groups.projects.forEach((project) => project.threads.forEach(push));
    DATE_BUCKETS.forEach((bucket) => groups.chats[bucket].forEach(push));

    return ordered;
}

export function nextThreadAfterDelete(
    threads: readonly NovaThreadSummary[],
    deletedId: string,
): string | null {
    const index = threads.findIndex((thread) => thread.id === deletedId);
    if (index < 0) return null;
    return threads[index + 1]?.id ?? threads[index - 1]?.id ?? null;
}
