import { startTransition, useEffect, useRef, useState } from "react";

import {
    readStoredAgentKey,
    writeStoredAgentKey,
} from "../../lib/agent-preference";
import { DEFAULT_AGENT_KEY } from "../../lib/nova-constants";
import type { NovaAgent } from "../../types/nova";

export interface AgentSelection {
    agents: NovaAgent[];
    setAgents: React.Dispatch<React.SetStateAction<NovaAgent[]>>;
    selectedAgentKey: string;
    setSelectedAgentKey: React.Dispatch<React.SetStateAction<string>>;
    selectAgent: (agentKey: string) => void;
    syncAgentForThread: (agentKey: string | null | undefined) => void;
    handleAgentsChanged: (nextAgents: NovaAgent[]) => void;
}

/**
 * Own the agent catalog and the selected main-agent key with localStorage
 * persistence. `syncAgentForThread` adopts a thread's agent when it maps to a
 * known main agent; `handleAgentsChanged` falls back to the default when the
 * current selection disappears.
 */
export function useAgentSelection(): AgentSelection {
    const [agents, setAgents] = useState<NovaAgent[]>([]);
    const [selectedAgentKey, setSelectedAgentKey] = useState<string>(() =>
        readStoredAgentKey(),
    );
    const agentsRef = useRef<NovaAgent[]>([]);

    useEffect(() => {
        agentsRef.current = agents;
    }, [agents]);

    function selectAgent(agentKey: string) {
        setSelectedAgentKey(agentKey);
        writeStoredAgentKey(agentKey);
    }

    function syncAgentForThread(agentKey: string | null | undefined) {
        if (!agentKey) {
            return;
        }
        const known = agentsRef.current.some(
            (agent) => agent.key === agentKey && agent.kind === "main",
        );
        if (known) {
            selectAgent(agentKey);
        }
    }

    function handleAgentsChanged(nextAgents: NovaAgent[]) {
        startTransition(() => {
            setAgents(nextAgents);
            const selectedKnown = nextAgents.some(
                (agent) =>
                    agent.key === selectedAgentKey && agent.kind === "main",
            );
            if (!selectedKnown) {
                setSelectedAgentKey(DEFAULT_AGENT_KEY);
                writeStoredAgentKey(DEFAULT_AGENT_KEY);
            }
        });
    }

    return {
        agents,
        setAgents,
        selectedAgentKey,
        setSelectedAgentKey,
        selectAgent,
        syncAgentForThread,
        handleAgentsChanged,
    };
}
