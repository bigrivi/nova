/** Sessions screen: browse/load persisted sessions */
import { listMessages, listSessions } from "../../api/nova-api.ts";
import type { NovaSessionSummary } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { recordsToMessages } from "../../utils/history.ts";
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

export function SessionsScreen() {
    const workspaceDir = WORKSPACE_DIR;
    const currentSessionId = useChatStore((state) => state.sessionId);
    const folder = workspaceDir.split("/").filter(Boolean).at(-1) ?? workspaceDir;
    const { items: sessions, ready, error, initialIndex } = useListScreen(() =>
        listSessions({ workspaceDir }),
        (items) => items.findIndex((session) => session.id === currentSessionId),
    );

    async function handleSelect(session: NovaSessionSummary): Promise<void> {
        useScreenStore.getState().close();
        try {
            const records = await listMessages(session.id);
            const messages = recordsToMessages(records);
            useChatStore.getState().loadHistory(session.id, messages);
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
            items={sessions}
            filter={(session, query) =>
                !query ||
                (session.title ?? "")
                    .toLowerCase()
                    .includes(query.toLowerCase())
            }
            onSelect={(session) => void handleSelect(session)}
            onClose={() => useScreenStore.getState().close()}
            renderLabel={(session) =>
                `${session.title ?? "(untitled)"}  —  ${formatTime(session.updated_at)}`
            }
            initialIndex={initialIndex}
            emptyText={error || "no sessions in this folder yet"}
        />
    );
}
