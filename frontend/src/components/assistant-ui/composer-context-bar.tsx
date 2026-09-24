/* eslint-disable react-refresh/only-export-components */
import { Folder, X } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { NovaAgent } from "../../types/nova";
import {
    ModelSelectorContent,
    ModelSelectorEmpty,
    ModelSelectorItem,
    ModelSelectorList,
    ModelSelectorRoot,
    ModelSelectorSearch,
    ModelSelectorTrigger,
    type ModelOption,
} from "./elements/model-selector";

const AVATAR_PALETTE = [
    "#1D5FA8",
    "#6D4AA0",
    "#0E7C6B",
    "#B0562A",
    "#A8325A",
    "#4A6B2A",
    "#8A6D1B",
    "#3A6EA5",
];

export function agentAvatarColor(key: string): string {
    let hash = 0;
    for (let i = 0; i < key.length; i += 1) {
        hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
    }
    return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

export function AgentAvatar({
    agentKey,
    name,
    size = "sm",
}: {
    agentKey: string;
    name: string;
    size?: "sm" | "md";
}) {
    const color = agentAvatarColor(agentKey || name || "?");
    const initial = (name || agentKey || "?").trim().charAt(0) || "?";
    const sizeClass =
        size === "md"
            ? "size-7 rounded-[9px] text-[13px]"
            : "size-[18px] rounded-[5.5px] text-[11px]";
    return (
        <span
            aria-hidden
            className={`inline-flex shrink-0 items-center justify-center font-bold leading-none text-white ${sizeClass}`}
            style={{ backgroundColor: color, borderColor: color }}
        >
            {initial}
        </span>
    );
}

function chattable(agents: NovaAgent[]): NovaAgent[] {
    return agents.filter((agent) =>
        agent.mode != null ? agent.mode === "primary" : agent.kind === "main",
    );
}

function ComposerAgentSelect({
    agents,
    selectedAgentKey,
    onSelect,
}: {
    agents: NovaAgent[];
    selectedAgentKey: string | null;
    onSelect: (agentKey: string) => void;
}) {
    const { t } = useTranslation();
    const list = useMemo(() => chattable(agents), [agents]);
    const selected =
        list.find((agent) => agent.key === selectedAgentKey) ?? null;
    const options = useMemo<ModelOption[]>(
        () =>
            list.map((agent) => ({
                id: agent.key,
                name: agent.name || agent.key,
                description: agent.description || undefined,
                icon: (
                    <AgentAvatar
                        agentKey={agent.key}
                        name={agent.name || agent.key}
                        size="md"
                    />
                ),
                keywords: [
                    agent.name,
                    agent.key,
                    agent.description ?? "",
                ],
            })),
        [list],
    );

    return (
        <ModelSelectorRoot
            models={options}
            value={selectedAgentKey ?? undefined}
            onValueChange={onSelect}
        >
            <ModelSelectorTrigger
                aria-label={t("agentSelector.activeAgent")}
                title={selected?.name ?? t("agentSelector.noAgentsAvailable")}
                size="sm"
                className="h-auto gap-1.5 rounded-md border-0 bg-transparent px-[7px] py-[2px] text-[12.5px] font-medium text-muted-foreground shadow-none hover:bg-muted/60 hover:text-primary focus:bg-accent/60 focus:text-primary [&_svg]:size-3"
            >
                {selected ? (
                    <span className="flex min-w-0 items-center gap-1.5">
                        <AgentAvatar
                            agentKey={selected.key}
                            name={selected.name || selected.key}
                        />
                        <span className="truncate">
                            @{selected.name || selected.key}
                        </span>
                    </span>
                ) : (
                    <span className="text-muted-foreground">
                        {t("agentSelector.noAgentsAvailable")}
                    </span>
                )}
            </ModelSelectorTrigger>
            <ModelSelectorContent align="start" searchable>
                <ModelSelectorSearch
                    placeholder={t("agentSelector.searchAgents")}
                />
                <ModelSelectorList>
                    <ModelSelectorEmpty>
                        {t("agentSelector.noMatchingAgents")}
                    </ModelSelectorEmpty>
                    {options.map((option) => (
                        <ModelSelectorItem key={option.id} model={option} />
                    ))}
                </ModelSelectorList>
            </ModelSelectorContent>
        </ModelSelectorRoot>
    );
}

export type ComposerContextBarProps = {
    isNewChat: boolean;
    agents: NovaAgent[];
    selectedAgentKey: string | null;
    onSelectAgent: (agentKey: string) => void;
    sessionAgentKey: string | null;
    draftProjectName: string | null;
    sessionProjectName: string | null;
    onRemoveProject: () => void;
};

export function ComposerContextBar({
    isNewChat,
    agents,
    selectedAgentKey,
    onSelectAgent,
    sessionAgentKey,
    draftProjectName,
    sessionProjectName,
    onRemoveProject,
}: ComposerContextBarProps) {
    const { t } = useTranslation();

    if (isNewChat) {
        if (!draftProjectName) {
            return (
                <div className="flex items-center py-2">
                    <ComposerAgentSelect
                        agents={agents}
                        selectedAgentKey={selectedAgentKey}
                        onSelect={onSelectAgent}
                    />
                </div>
            );
        }
        return (
            <div className="flex items-center py-2">
                <ComposerAgentSelect
                    agents={agents}
                    selectedAgentKey={selectedAgentKey}
                    onSelect={onSelectAgent}
                />
                <span
                    aria-hidden
                    className="mx-[7px] ml-[5px] h-3.5 w-px shrink-0 bg-border"
                />
                <span className="flex min-w-0 items-center gap-[5px] rounded-md py-[2px] pl-[7px] pr-[3px] text-[12.5px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground">
                    <Folder
                        aria-hidden
                        className="block size-3 shrink-0 opacity-60"
                    />
                    <span
                        className="max-w-40 truncate"
                        title={draftProjectName}
                    >
                        {draftProjectName}
                    </span>
                    <button
                        type="button"
                        onClick={onRemoveProject}
                        title={t("composer.removeProject")}
                        aria-label={t("composer.removeProject")}
                        className="inline-flex size-[18px] shrink-0 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-primary/10 hover:text-primary"
                    >
                        <X className="size-2.5" />
                    </button>
                </span>
            </div>
        );
    }

    const sessionAgent =
        agents.find((agent) => agent.key === sessionAgentKey) ?? null;
    const agentLabel = sessionAgent
        ? (sessionAgent.name || sessionAgent.key)
        : (sessionAgentKey ?? selectedAgentKey ?? "");
    const avatarKey = sessionAgent?.key ?? sessionAgentKey ?? "agent";
    return (
        <div className="flex min-w-0 items-center py-2">
            <span
                title={t("composer.agentFixed")}
                className="inline-flex shrink-0 cursor-default select-none items-center gap-1.5 rounded-md px-[7px] py-[2px] text-[12.5px] font-medium text-muted-foreground opacity-80"
            >
                <AgentAvatar agentKey={avatarKey} name={agentLabel || "?"} />
                <span className="truncate">@{agentLabel}</span>
            </span>
            {sessionProjectName ? (
                <>
                    <span
                        aria-hidden
                        className="mx-[7px] ml-[5px] h-3.5 w-px shrink-0 bg-border"
                    />
                    <span
                        title={sessionProjectName}
                        className="inline-flex min-w-0 cursor-default select-none items-center gap-[5px] rounded-md px-[7px] py-[2px] text-[12.5px] text-muted-foreground opacity-80"
                    >
                        <Folder
                            aria-hidden
                            className="block size-3 shrink-0 opacity-60"
                        />
                        <span className="max-w-50 truncate">
                            {sessionProjectName}
                        </span>
                    </span>
                </>
            ) : null}
        </div>
    );
}
