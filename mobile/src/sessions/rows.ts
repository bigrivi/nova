/** Session list rows: pinned, projects, date buckets, or a flat search. */
import type { NovaProject, NovaSessionSummary } from "../api/types";
import { dateBucket, DATE_BUCKETS, DATE_BUCKET_LABELS } from "../lib/date-bucket";
import { filterSessionsByTitle } from "../lib/session-search";

export type Row =
    | {
          key: string;
          kind: "header";
          title: string;
          createProject?: boolean;
      }
    | {
          key: string;
          kind: "project";
          project: NovaProject;
          count: number;
          expanded: boolean;
      }
    | { key: string; kind: "project-empty"; project: NovaProject }
    | {
          key: string;
          kind: "session";
          session: NovaSessionSummary;
          indented: boolean;
      }
    | { key: string; kind: "empty"; title: string; body: string };

function sessionRows(
    sessions: readonly NovaSessionSummary[],
    prefix: string,
    indented: boolean,
): Row[] {
    return sessions.map((session) => ({
        key: `${prefix}-${session.id}`,
        kind: "session",
        session,
        indented,
    }));
}

/**
 * Build the scrollable row list.
 *
 * A non-blank query switches to a flat, title-matched result list; otherwise
 * pinned chats come first, then projects, then ungrouped chats in date buckets.
 *
 * @param items Sessions from the server.
 * @param projects Projects, in creation order.
 * @param expanded Project ids currently expanded.
 * @param query Raw search box text.
 * @returns Rows ready for the FlatList.
 */
export function buildSessionRows({
    items,
    projects,
    expanded,
    query,
}: {
    items: readonly NovaSessionSummary[];
    projects: readonly NovaProject[];
    expanded: ReadonlySet<string>;
    query: string;
}): Row[] {
    const sorted = [...items].sort((a, b) => b.updated_at - a.updated_at);
    const searching = query.trim().length > 0;
    if (searching) {
        const matches = filterSessionsByTitle(sorted, query);
        if (matches.length === 0) {
            return [
                {
                    key: "empty-search",
                    kind: "empty",
                    title: "No matches",
                    body: `No conversation title contains "${query.trim()}".`,
                },
            ];
        }
        return [
            {
                key: "header-results",
                kind: "header",
                title: `${matches.length} result${matches.length === 1 ? "" : "s"}`,
            },
            ...sessionRows(matches, "search", false),
        ];
    }

    const pinned = sorted.filter((session) => session.pinned);
    const unpinned = sorted.filter((session) => !session.pinned);
    const byProject = new Map<string, NovaSessionSummary[]>(
        projects.map((project) => [project.id, []]),
    );
    const unprojected: NovaSessionSummary[] = [];
    for (const session of unpinned) {
        const bucket = session.project_id
            ? byProject.get(session.project_id)
            : undefined;
        if (bucket) {
            bucket.push(session);
        } else {
            unprojected.push(session);
        }
    }

    const orderedProjects = projects
        .map((project) => {
            const sessions = byProject.get(project.id) ?? [];
            const latest = sessions.length
                ? Math.max(...sessions.map((item) => item.updated_at))
                : project.updated_at;
            return { project, sessions, latest };
        })
        .sort((left, right) => right.latest - left.latest);

    const rows: Row[] = [];
    if (pinned.length > 0) {
        rows.push({
            key: "header-pinned",
            kind: "header",
            title: "Pinned",
        });
        rows.push(...sessionRows(pinned, "pinned", false));
    }

    rows.push({
        key: "header-projects",
        kind: "header",
        title: "Projects",
        createProject: true,
    });
    for (const { project, sessions } of orderedProjects) {
        const open = expanded.has(project.id);
        rows.push({
            key: `project-${project.id}`,
            kind: "project",
            project,
            count: sessions.length,
            expanded: open,
        });
        if (!open) {
            continue;
        }
        if (sessions.length === 0) {
            rows.push({
                key: `project-empty-${project.id}`,
                kind: "project-empty",
                project,
            });
        } else {
            rows.push(...sessionRows(sessions, `project-${project.id}`, true));
        }
    }

    rows.push({
        key: "header-chats",
        kind: "header",
        title: "Chats",
    });
    if (unprojected.length === 0) {
        rows.push({
            key: "empty-chats",
            kind: "empty",
            title: "No conversations yet",
            body:
                items.length === 0 && projects.length === 0
                    ? "Start a conversation or create a project to group them."
                    : "Ungrouped conversations appear here.",
        });
        return rows;
    }

    const buckets: Record<string, NovaSessionSummary[]> = {
        today: [],
        yesterday: [],
        last7Days: [],
        older: [],
    };
    for (const session of unprojected) {
        buckets[dateBucket(session.updated_at)]?.push(session);
    }
    for (const bucket of DATE_BUCKETS) {
        const group = buckets[bucket] ?? [];
        if (group.length === 0) {
            continue;
        }
        rows.push({
            key: `header-${bucket}`,
            kind: "header",
            title: DATE_BUCKET_LABELS[bucket],
        });
        rows.push(...sessionRows(group, bucket, false));
    }
    return rows;
}
