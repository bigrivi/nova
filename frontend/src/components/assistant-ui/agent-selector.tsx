import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
    ModelSelectorContent,
    ModelSelectorEmpty,
    ModelSelectorItem,
    ModelSelectorList,
    ModelSelectorRoot,
    ModelSelectorSearch,
    ModelSelectorTrigger,
    ModelSelectorValue,
    type ModelOption,
} from "./elements/model-selector";

import type { NovaAgent } from "../../types/nova";

type AgentSelectorProps = {
    agents: NovaAgent[];
    selectedAgentKey: string | null;
    onSelect: (agentKey: string) => void;
};

export function AgentSelector({
    agents,
    selectedAgentKey,
    onSelect,
}: AgentSelectorProps) {
    const { t } = useTranslation();
    const selectId = "nova-agent-select";
    const chattableAgents = useMemo(
        () =>
            agents.filter((agent) =>
                agent.mode != null
                    ? agent.mode === "primary"
                    : agent.kind === "main",
            ),
        [agents],
    );
    const selectedAgent = chattableAgents.find(
        (agent) => agent.key === selectedAgentKey,
    );
    const agentOptions = useMemo<ModelOption[]>(
        () =>
            chattableAgents.map((agent) => ({
                id: agent.key,
                name: agent.name || agent.key,
                description: agent.description || undefined,
                keywords: [
                    agent.name,
                    agent.key,
                    agent.description ?? "",
                ],
            })),
        [chattableAgents],
    );

    function toAgentOption(agent: NovaAgent): ModelOption {
        return (
            agentOptions.find((option) => option.id === agent.key) ?? {
                id: agent.key,
                name: agent.name || agent.key,
            }
        );
    }

    return (
        <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor={selectId}>
                {t("agentSelector.activeAgent")}
            </label>
            <ModelSelectorRoot
                models={agentOptions}
                value={selectedAgentKey ?? undefined}
                onValueChange={onSelect}
            >
                <ModelSelectorTrigger
                    id={selectId}
                    aria-label={t("agentSelector.activeAgent")}
                    title={
                        selectedAgent?.name ||
                        t("agentSelector.noAgentsAvailable")
                    }
                    size="sm"
                    className="h-8 w-auto max-w-[240px] rounded-full border-border/60 bg-background/85 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/35 hover:text-muted-foreground focus:bg-background focus:text-foreground"
                >
                    <ModelSelectorValue
                        placeholder={t("agentSelector.noAgentsAvailable")}
                        showEffort={false}
                    />
                </ModelSelectorTrigger>
                <ModelSelectorContent
                    align="end"
                    searchable
                    className="max-w-[calc(100vw-2rem)]"
                >
                    <ModelSelectorSearch
                        placeholder={t("agentSelector.searchAgents")}
                    />
                    <ModelSelectorList>
                        <ModelSelectorEmpty>
                            {t("agentSelector.noMatchingAgents")}
                        </ModelSelectorEmpty>
                        {chattableAgents.map((agent) => (
                            <ModelSelectorItem
                                key={agent.key}
                                model={toAgentOption(agent)}
                            />
                        ))}
                    </ModelSelectorList>
                </ModelSelectorContent>
            </ModelSelectorRoot>
        </div>
    );
}
