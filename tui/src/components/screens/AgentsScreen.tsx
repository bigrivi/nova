/** Agents screen: browse the agent list (Enter on an agent = delete it) */
import { useEffect, useState } from "react";
import type { NovaAgentRecord } from "../../api/types.ts";
import { deleteAgent, listAgents } from "../../api/nova-api.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { SearchableList } from "./SearchableList.tsx";

export function AgentsScreen({ deletable }: { deletable: boolean }) {
    const [agents, setAgents] = useState<NovaAgentRecord[]>([]);
    const [error, setError] = useState("");

    useEffect(() => {
        void reload();
    }, []);

    async function reload(): Promise<void> {
        try {
            setAgents(await listAgents());
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        }
    }

    async function handleSelect(agent: NovaAgentRecord): Promise<void> {
        if (!deletable) {
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
        />
    );
}
