import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { deleteAgent, listAgents } from "../../../lib/nova-api";
import type {
    NovaAgent,
    NovaAgentMode,
    NovaModelRecord,
} from "../../../types/nova";
import { Button } from "../../ui/button";
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../../ui/dialog";
import { AgentDialog } from "./agent-dialog";

export type AgentsManagerDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    agents: NovaAgent[];
    models: NovaModelRecord[];
    onAgentsChanged: (agents: NovaAgent[]) => void;
};

const MODE_ORDER: NovaAgentMode[] = ["primary", "subagent"];

const MODE_LABEL_KEY: Record<NovaAgentMode, string> = {
    primary: "agentManager.primaryAgents",
    subagent: "agentManager.subagentAgents",
};

function agentModeOf(agent: NovaAgent): NovaAgentMode {
    if (agent.mode === "primary" || agent.mode === "subagent") {
        return agent.mode;
    }
    return agent.kind === "sub" ? "subagent" : "primary";
}

function agentParentsOf(agent: NovaAgent): string[] {
    return Array.isArray(agent.parents) ? agent.parents : [];
}

function canDelete(agent: NovaAgent): boolean {
    return agent.kind !== "main";
}

function AgentRow({
    agent,
    agents,
    models,
    onEdit,
    onDelete,
}: {
    agent: NovaAgent;
    agents: NovaAgent[];
    models: NovaModelRecord[];
    onEdit: () => void;
    onDelete: () => void;
}) {
    const { t } = useTranslation();
    const modelLabel = useMemo(() => {
        if (!agent.provider || !agent.model) {
            return t("agentManager.noModel");
        }
        const match = models.find(
            (model) =>
                model.provider === agent.provider &&
                model.model === agent.model,
        );
        return match?.label ?? `${agent.provider}:${agent.model}`;
    }, [agent, models, t]);
    const deletable = canDelete(agent);
    const isSubagent = agentModeOf(agent) === "subagent";
    const parentsLabel = useMemo(() => {
        if (!isSubagent) {
            return null;
        }
        const parents = agentParentsOf(agent);
        if (parents.length === 0) {
            return null;
        }
        const names = parents.map((parentKey) => {
            const match = agents.find((item) => item.key === parentKey);
            return match?.name || match?.key || parentKey;
        });
        return t("agentManager.belongsTo", { parents: names.join(", ") });
    }, [agent, agents, isSubagent, t]);

    return (
        <div className="rounded-lg border bg-card p-3">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate text-sm font-medium">
                            {agent.name || agent.key}
                        </span>
                        <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                            {agent.key}
                        </span>
                        {isSubagent && agent.posture ? (
                            <span className="rounded bg-muted/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">
                                {agent.posture === "read_only"
                                    ? t("agentManager.postureReadOnly")
                                    : t("agentManager.postureFull")}
                            </span>
                        ) : null}
                    </div>
                    {parentsLabel ? (
                        <p className="mt-0.5 truncate text-xs text-muted-foreground/70">
                            {parentsLabel}
                        </p>
                    ) : null}
                    {agent.description ? (
                        <p className="mt-1 break-words text-sm text-muted-foreground">
                            {agent.description}
                        </p>
                    ) : null}
                    <p className="mt-0.5 truncate text-xs text-muted-foreground/70">
                        {modelLabel}
                    </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("modelSelector.edit")}
                        title={t("modelSelector.edit")}
                        onClick={onEdit}
                    >
                        <PencilIcon className="size-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("modelSelector.delete")}
                        title={
                            deletable
                                ? t("modelSelector.delete")
                                : t("agentManager.cannotDelete")
                        }
                        disabled={!deletable}
                        onClick={onDelete}
                    >
                        <Trash2Icon className="size-4" />
                    </Button>
                </div>
            </div>
        </div>
    );
}

export function AgentsManagerDialog({
    open,
    onOpenChange,
    agents,
    models,
    onAgentsChanged,
}: AgentsManagerDialogProps) {
    const { t } = useTranslation();
    const [dialogMode, setDialogMode] = useState<
        { type: "create" } | { type: "edit"; agent: NovaAgent } | null
    >(null);
    const [agentToDelete, setAgentToDelete] = useState<NovaAgent | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState<string | null>(null);
    const [actionError, setActionError] = useState<string | null>(null);

    async function handleConfirmDelete() {
        if (!agentToDelete) {
            return;
        }
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteAgent(agentToDelete.key);
            onAgentsChanged(await listAgents());
            setAgentToDelete(null);
        } catch (error) {
            setDeleteError(
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            setDeleting(false);
        }
    }

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>
                            {t("agentManager.manageAgents")}
                        </DialogTitle>
                        <DialogDescription>
                            {t("agentManager.manageDescription")}
                        </DialogDescription>
                    </DialogHeader>
                    <div className="max-h-[60vh] overflow-y-auto pr-1">
                        {agents.length === 0 ? (
                            <p className="py-6 text-center text-sm text-muted-foreground">
                                {t("agentManager.empty")}
                            </p>
                        ) : null}
                        {MODE_ORDER.map((agentMode) => {
                            const group = agents.filter(
                                (agent) => agentModeOf(agent) === agentMode,
                            );
                            if (group.length === 0) {
                                return null;
                            }
                            return (
                                <div key={agentMode} className="mb-4 last:mb-0">
                                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                        {t(MODE_LABEL_KEY[agentMode])} (
                                        {group.length})
                                    </h3>
                                    <div className="flex flex-col gap-2">
                                        {group.map((agent) => (
                                            <AgentRow
                                                key={agent.key}
                                                agent={agent}
                                                agents={agents}
                                                models={models}
                                                onEdit={() => {
                                                    setActionError(null);
                                                    setDialogMode({
                                                        type: "edit",
                                                        agent,
                                                    });
                                                }}
                                                onDelete={() => {
                                                    setDeleteError(null);
                                                    setAgentToDelete(agent);
                                                }}
                                            />
                                        ))}
                                    </div>
                                </div>
                            );
                        })}
                        {actionError ? (
                            <p className="mt-2 text-xs text-destructive">
                                {actionError}
                            </p>
                        ) : null}
                    </div>
                    <DialogFooter>
                        <Button
                            type="button"
                            size="sm"
                            onClick={() => {
                                setActionError(null);
                                setDialogMode({ type: "create" });
                            }}
                        >
                            <PlusIcon className="size-4" />
                            {t("agentManager.createAgent")}
                        </Button>
                        <DialogClose asChild>
                            <Button type="button" variant="outline">
                                {t("common.close")}
                            </Button>
                        </DialogClose>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {dialogMode ? (
                <AgentDialog
                    key={
                        dialogMode.type === "edit"
                            ? dialogMode.agent.key
                            : "create"
                    }
                    open={dialogMode !== null}
                    onOpenChange={(next) => {
                        if (!next) {
                            setDialogMode(null);
                        }
                    }}
                    mode={dialogMode}
                    agents={agents}
                    models={models}
                    onMutated={(nextAgents) => {
                        onAgentsChanged(nextAgents);
                        setActionError(null);
                    }}
                />
            ) : null}

            <Dialog
                open={agentToDelete !== null}
                onOpenChange={(next) => {
                    if (!next) {
                        setAgentToDelete(null);
                        setDeleteError(null);
                    }
                }}
            >
                <DialogContent className="sm:max-w-sm">
                    <DialogHeader>
                        <DialogTitle>
                            {t("agentManager.deleteConfirmTitle")}
                        </DialogTitle>
                        <DialogDescription>
                            {t("agentManager.deleteConfirmDescription", {
                                key: agentToDelete?.key ?? "",
                            })}
                        </DialogDescription>
                    </DialogHeader>
                    {deleteError ? (
                        <p className="text-sm text-destructive">
                            {deleteError}
                        </p>
                    ) : null}
                    <DialogFooter>
                        <DialogClose asChild>
                            <Button type="button" variant="outline">
                                {t("common.cancel")}
                            </Button>
                        </DialogClose>
                        <Button
                            type="button"
                            variant="destructive"
                            disabled={deleting}
                            onClick={() => void handleConfirmDelete()}
                        >
                            {deleting
                                ? t("agentManager.deleting")
                                : t("modelSelector.delete")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}
