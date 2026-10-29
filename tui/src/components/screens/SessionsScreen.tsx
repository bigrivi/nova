/** Sessions screen: browse/load persisted sessions, forks nested under their origin */
import { listSessions } from "../../api/nova-api.ts";
import type { NovaSessionSummary } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { openSession } from "../../lib/open-session.ts";
import { WORKSPACE_DIR } from "../../workspace.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { useListScreen } from "./use-list-screen.ts";

function formatTime(ms: number): string {
    const diff = Date.now() - ms;
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return new Date(ms).toLocaleDateString();
}

export type SessionRow = {
    id: string;
    title: string;
    updatedAt: number;
    /** Header this row sits under; only forks get one. */
    group?: string;
    /** True for a fork, so the label can carry the branch marker. */
    isFork: boolean;
};

/**
 * Order sessions for the grouped list: an origin followed by its forks.
 *
 * The list component only draws a header when the group label *changes*, so the
 * array has to be contiguous per group. A fork whose origin is not in the
 * current folder (the list is filtered by workspace) still gets a row, just
 * without a header: hiding a conversation is worse than an unlabelled one.
 */
export function arrangeSessions(sessions: NovaSessionSummary[]): SessionRow[] {
    const byId = new Map(sessions.map((session) => [session.id, session]));
    const forksByOrigin = new Map<string, NovaSessionSummary[]>();
    for (const session of sessions) {
        const origin = session.forked_from;
        if (!origin || !byId.has(origin)) continue;
        const existing = forksByOrigin.get(origin) ?? [];
        existing.push(session);
        forksByOrigin.set(origin, existing);
    }

    const rows: SessionRow[] = [];
    for (const session of sessions) {
        // A fork is emitted by its origin, never on its own.
        if (session.forked_from && byId.has(session.forked_from)) continue;
        rows.push({
            id: session.id,
            title: session.title ?? "(untitled)",
            updatedAt: session.updated_at,
            isFork: false,
        });
        for (const fork of forksByOrigin.get(session.id) ?? []) {
            rows.push({
                id: fork.id,
                title: fork.title ?? "(untitled)",
                updatedAt: fork.updated_at,
                group: `from ${session.title ?? "(untitled)"}`,
                isFork: true,
            });
        }
    }
    return rows;
}

export function SessionsScreen() {
    const workspaceDir = WORKSPACE_DIR;
    const currentSessionId = useChatStore((state) => state.sessionId);
    const folder = workspaceDir.split("/").filter(Boolean).at(-1) ?? workspaceDir;
    const { items: sessions, ready, error, defaultValue } = useListScreen(
        () => listSessions({ workspaceDir }),
        (items) => items.find((s) => s.id === currentSessionId)?.id,
    );

    async function handleSelect(value: string): Promise<void> {
        useScreenStore.getState().close();
        try {
            await openSession(value);
        } catch (err) {
            useChatStore
                .getState()
                .failStream(err instanceof Error ? err.message : String(err));
        }
    }

    if (!ready) {
        return <ScreenLoading message={error || "Loading sessions..."} />;
    }

    return (
        <SearchableList
            title={`Sessions · ${folder}`}
            items={arrangeSessions(sessions).map((row) => ({
                label: row.isFork ? `└ ${row.title}` : row.title,
                value: row.id,
                group: row.group,
                updatedAt: row.updatedAt,
            }))}
            renderLabel={(row) =>
                `${row.label}  —  ${formatTime(row.updatedAt)}`
            }
            onSelect={(value) => void handleSelect(value)}
            onClose={() => useScreenStore.getState().close()}
            defaultValue={defaultValue}
            emptyText={error || "no sessions in this folder yet"}
        />
    );
}
