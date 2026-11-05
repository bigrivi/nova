/** Sessions screen: browse/load persisted sessions, forks nested under their origin */
import { listPendingSessions, listSessions } from "../../api/nova-api.ts";
import type {
    NovaPendingSummary,
    NovaSessionSummary,
} from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { openSession } from "../../lib/open-session.ts";
import { WORKSPACE_DIR } from "../../workspace.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { SearchableList } from "./SearchableList.tsx";
import { useListScreen } from "./use-list-screen.ts";

export type SessionPending = "approval" | "question" | null;

export type SessionListEntry = NovaSessionSummary & {
    pending?: SessionPending;
};

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
    /** A prompt this session is still waiting on. */
    pending: SessionPending;
};

/**
 * Order sessions for the grouped list: an origin followed by its forks.
 *
 * The list component only draws a header when the group label *changes*, so the
 * array has to be contiguous per group. A fork whose origin is not in the
 * current folder (the list is filtered by workspace) still gets a row, just
 * without a header: hiding a conversation is worse than an unlabelled one.
 *
 * Sessions with a pending approval or question rank above the rest, then the
 * newest origin first; equal keys keep the server's order.
 */
export function arrangeSessions(sessions: SessionListEntry[]): SessionRow[] {
    const byId = new Map(sessions.map((session) => [session.id, session]));
    const forksByOrigin = new Map<string, SessionListEntry[]>();
    for (const session of sessions) {
        const origin = session.forked_from;
        if (!origin || !byId.has(origin)) continue;
        const existing = forksByOrigin.get(origin) ?? [];
        existing.push(session);
        forksByOrigin.set(origin, existing);
    }

    const groups = sessions
        .filter(
            (session) =>
                !(session.forked_from && byId.has(session.forked_from)),
        )
        .map((origin) => ({
            origin,
            forks: forksByOrigin.get(origin.id) ?? [],
        }));
    groups.sort((a, b) => {
        const rank = (entry: SessionListEntry) =>
            entry.pending ? 1 : 0;
        const rankDelta = rank(b.origin) - rank(a.origin);
        if (rankDelta !== 0) return rankDelta;
        return b.origin.updated_at - a.origin.updated_at;
    });

    const rows: SessionRow[] = [];
    for (const { origin, forks } of groups) {
        rows.push({
            id: origin.id,
            title: origin.title ?? "(untitled)",
            updatedAt: origin.updated_at,
            isFork: false,
            pending: origin.pending ?? null,
        });
        for (const fork of forks) {
            rows.push({
                id: fork.id,
                title: fork.title ?? "(untitled)",
                updatedAt: fork.updated_at,
                group: `from ${origin.title ?? "(untitled)"}`,
                isFork: true,
                pending: fork.pending ?? null,
            });
        }
    }
    return rows;
}

export function pendingMark(pending: SessionPending): string {
    if (pending === "approval") return "! ";
    if (pending === "question") return "? ";
    return "";
}

export function SessionsScreen() {
    const workspaceDir = WORKSPACE_DIR;
    const currentSessionId = useChatStore((state) => state.sessionId);
    const folder = workspaceDir.split("/").filter(Boolean).at(-1) ?? workspaceDir;
    const { items: sessions, ready, error, defaultValue } = useListScreen(
        async () => {
            const [list, pending] = await Promise.all([
                listSessions({ workspaceDir }),
                listPendingSessions().catch(
                    (): NovaPendingSummary => ({}),
                ),
            ]);
            return list.map((session) => {
                const state = pending[session.id];
                return {
                    ...session,
                    pending: state?.ask
                        ? ("question" as const)
                        : state?.approvals
                          ? ("approval" as const)
                          : null,
                };
            });
        },
        (items) => items.find((s) => s.id === currentSessionId)?.id,
    );

    async function handleSelect(value: string): Promise<void> {
        useScreenStore.getState().close();
        const selected = sessions.find((session) => session.id === value);
        const agentKey = selected?.agent_key;
        try {
            await openSession(
                value,
                agentKey,
                undefined,
                selected?.title ?? undefined,
            );
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
                label: `${pendingMark(row.pending)}${row.isFork ? "└ " : ""}${row.title}`,
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
