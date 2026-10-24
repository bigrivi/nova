/** Agents screen: browse and switch the active main agent (Enter on an agent
 *  in delete mode removes it). */
import type { NovaAgentRecord } from "../../api/types.ts";
import { deleteAgent, listAgents } from "../../api/nova-api.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { SearchableList } from "./SearchableList.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { useListScreen } from "./use-list-screen.ts";

export function AgentsScreen({ deletable }: { deletable: boolean }) {
    const currentAgentKey = useChatStore((state) => state.agentKey);
    const { items: agents, ready, error, initialIndex, reload } = useListScreen(
        async () =>
            (await listAgents()).filter((agent) => agent.kind !== "sub"),
        (items) => items.findIndex((agent) => agent.key === currentAgentKey),
    );

    async function handleSelect(agent: NovaAgentRecord): Promise<void> {
        if (!deletable) {
            useChatStore.setState({
                agentKey: agent.key,
                agentName: agent.name,
                ...(agent.provider && agent.model
                    ? { provider: agent.provider, model: agent.model }
                    : {}),
            });
            useScreenStore.getState().close();
            return;
        }
        if (agent.key === "main") {
            useToastStore.getState().show("Cannot delete the main agent");
            return;
        }
        try {
            await deleteAgent(agent.key);
            reload();
        } catch (err) {
            useToastStore
                .getState()
                .show(err instanceof Error ? err.message : String(err));
        }
    }

    if (!ready) {
        return <ScreenLoading message={error || "Loading agents..."} />;
    }

    return (
        <SearchableList
            title={deletable ? "Delete Agent (select to delete)" : "Agents"}
            items={agents}
            filter={(agent, query) =>
                !query ||
                agent.key.includes(query) ||
                agent.name.toLowerCase().includes(query.toLowerCase())
            }
            renderLabel={(agent) =>
                `${agent.key}  —  ${agent.name}${agent.model ? `  [${agent.provider}/${agent.model}]` : ""}`
            }
            onSelect={(agent) => void handleSelect(agent)}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no agents"}
            initialIndex={initialIndex}
        />
    );
}
