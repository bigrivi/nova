/** Agents screen: browse the agent list (Enter on an agent = delete it) */
import { useEffect, useState } from "react";
import { deleteAgent, listAgents } from "../../api/nova-api.ts";
import type { NovaAgentRecord } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { SearchableList } from "./SearchableList.tsx";

export function AgentsScreen({ deletable }: { deletable: boolean }) {
    const theme = useTheme();
    const [agents, setAgents] = useState<NovaAgentRecord[]>([]);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        void reload();
    }, []);

    async function reload(): Promise<void> {
        try {
            const items = await listAgents();
            setAgents(items.filter((agent) => agent.kind !== "sub"));
            setLoaded(true);
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
    }

    async function handleSelect(agent: NovaAgentRecord): Promise<void> {
        if (!deletable) {
            useChatStore.setState({
                agentKey: agent.key,
                agentName: agent.name,
                ...(agent.provider && agent.model
                    ? { provider: agent.provider, model: agent.model }
                    : {}),
                ...(agent.provider_name ? { providerName: agent.provider_name } : {}),
                ...(agent.model_name ? { modelName: agent.model_name } : {}),
            });
            useScreenStore.getState().close();
            return;
        }
        if (agent.key === "main") {
            setError("cannot delete the main agent");
            return;
        }
        try {
            await deleteAgent(agent.key);
            await reload();
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
    }

    if (!loaded) {
        return (
            <box position="absolute" left="15%" right="15%" top="15%" paddingX={2} paddingY={2} border borderColor={theme?.accent ?? "#4f9cf9"} backgroundColor={theme?.surfaceDeep ?? "#0d1117"}>
                <text>Loading...</text>
            </box>
        );
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
                `${agent.key}  —  ${agent.name}`
            }
            onSelect={(agent) => void handleSelect(agent)}
            onClose={() => useScreenStore.getState().close()}
            emptyText={error || "no agents"}
            initialIndex={Math.max(0, agents.findIndex((a) => a.key === useChatStore.getState().agentKey))}
        />
    );
}
