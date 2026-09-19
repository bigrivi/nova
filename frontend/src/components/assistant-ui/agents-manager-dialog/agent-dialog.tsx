import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
    createAgent,
    listAgents,
    setAgentParents,
    updateAgent,
} from "../../../lib/nova-api";
import type {
    NovaAgent,
    NovaAgentMode,
    NovaAgentPosture,
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
import { inputClassName } from "../models-manager-dialog/types";

export const AGENT_KEY_PATTERN = /^[a-z0-9-]{3,32}$/;

type AgentDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    mode: { type: "create" } | { type: "edit"; agent: NovaAgent };
    agents: NovaAgent[];
    models: NovaModelRecord[];
    onMutated: (nextAgents: NovaAgent[]) => void;
};

function modelIdFor(model: NovaModelRecord): string {
    return `${model.provider}:${model.model}`;
}

function splitModelId(modelId: string): {
    provider: string;
    model: string;
} | null {
    const separator = modelId.indexOf(":");
    if (separator <= 0) {
        return null;
    }
    const provider = modelId.slice(0, separator);
    const model = modelId.slice(separator + 1);
    if (!provider || !model) {
        return null;
    }
    return { provider, model };
}

function agentModeOf(agent: NovaAgent): NovaAgentMode {
    if (agent.mode === "primary" || agent.mode === "subagent") {
        return agent.mode;
    }
    return agent.kind === "sub" ? "subagent" : "primary";
}

function agentParentsOf(agent: NovaAgent): string[] {
    return Array.isArray(agent.parents) ? agent.parents : [];
}

export function AgentDialog({
    open,
    onOpenChange,
    mode,
    agents,
    models,
    onMutated,
}: AgentDialogProps) {
    const { t } = useTranslation();
    const editing = mode.type === "edit" ? mode.agent : null;
    const editingMode = editing ? agentModeOf(editing) : null;

    const [key, setKey] = useState("");
    const [name, setName] = useState(editing?.name ?? "");
    const [description, setDescription] = useState(
        editing?.description ?? "",
    );
    const [modelId, setModelId] = useState(() => {
        if (editing?.provider && editing?.model) {
            const currentId = `${editing.provider}:${editing.model}`;
            if (models.some((model) => modelIdFor(model) === currentId)) {
                return currentId;
            }
        }
        return models[0] ? modelIdFor(models[0]) : "";
    });
    const [agentMode, setAgentMode] = useState<NovaAgentMode>(
        editing ? agentModeOf(editing) : "primary",
    );
    const [parentKeys, setParentKeys] = useState<string[]>(() =>
        editing ? agentParentsOf(editing) : [],
    );
    const [posture, setPosture] = useState<NovaAgentPosture>(
        editing?.posture ?? "full",
    );
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const isSubagent = editing ? editingMode === "subagent" : agentMode === "subagent";

    const primaryOptions = agents.filter(
        (agent) =>
            agentModeOf(agent) === "primary" &&
            agent.key !== editing?.key,
    );

    function toggleParent(parentKey: string) {
        setParentKeys((prev) =>
            prev.includes(parentKey)
                ? prev.filter((item) => item !== parentKey)
                : [...prev, parentKey],
        );
    }

    async function handleSave() {
        setError(null);
        const split = splitModelId(modelId);
        if (!split) {
            setError(t("agentManager.modelRequired"));
            return;
        }
        if (!editing && !AGENT_KEY_PATTERN.test(key)) {
            setError(t("agentManager.keyHint"));
            return;
        }
        if (!editing && !name.trim()) {
            setError(t("agentManager.nameRequired"));
            return;
        }
        setSaving(true);
        try {
            if (editing) {
                await updateAgent(editing.key, {
                    provider: split.provider,
                    model: split.model,
                });
                if (editingMode === "subagent") {
                    const nextParents = parentKeys.filter(
                        (parent) => parent !== editing.key,
                    );
                    const current = agentParentsOf(editing);
                    const changed =
                        nextParents.length !== current.length ||
                        nextParents.some(
                            (parent) => !current.includes(parent),
                        );
                    if (changed) {
                        await setAgentParents(editing.key, nextParents);
                    }
                }
            } else {
                const subagent = agentMode === "subagent";
                await createAgent({
                    key,
                    name: name.trim(),
                    description: description.trim(),
                    provider: split.provider,
                    model: split.model,
                    mode: agentMode,
                    posture: subagent ? posture : undefined,
                    parent_ids: subagent ? parentKeys : undefined,
                });
            }
            onMutated(await listAgents());
            onOpenChange(false);
        } catch (saveError) {
            setError(
                saveError instanceof Error
                    ? saveError.message
                    : String(saveError),
            );
        } finally {
            setSaving(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                        {editing
                            ? t("agentManager.editAgent")
                            : t("agentManager.createAgent")}
                    </DialogTitle>
                    <DialogDescription>
                        {editing
                            ? t("agentManager.editAgentDescription")
                            : t("agentManager.createAgentDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    {!editing ? (
                        <label className="block space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("agentManager.key")}
                            </span>
                            <input
                                value={key}
                                onChange={(event) =>
                                    setKey(event.target.value)
                                }
                                className={inputClassName}
                                placeholder={t(
                                    "agentManager.keyPlaceholder",
                                )}
                            />
                            <span className="block text-[11px] text-muted-foreground">
                                {t("agentManager.keyHint")}
                            </span>
                        </label>
                    ) : null}
                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("agentManager.name")}
                        </span>
                        <input
                            value={name}
                            onChange={(event) =>
                                setName(event.target.value)
                            }
                            className={inputClassName}
                            placeholder={t("agentManager.namePlaceholder")}
                        />
                    </label>
                    {!editing ? (
                        <label className="block space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("agentManager.description")}
                            </span>
                            <input
                                value={description}
                                onChange={(event) =>
                                    setDescription(event.target.value)
                                }
                                className={inputClassName}
                                placeholder={t(
                                    "agentManager.descriptionPlaceholder",
                                )}
                            />
                        </label>
                    ) : null}
                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("agentManager.model")}
                        </span>
                        <select
                            value={modelId}
                            onChange={(event) =>
                                setModelId(event.target.value)
                            }
                            className={inputClassName}
                        >
                            {models.length === 0 ? (
                                <option value="">
                                    {t("agentManager.noModelsAvailable")}
                                </option>
                            ) : null}
                            {models.map((model) => (
                                <option
                                    key={model.id}
                                    value={modelIdFor(model)}
                                >
                                    {model.provider_name
                                        ? `${model.provider_name} / ${model.label}`
                                        : model.label}
                                </option>
                            ))}
                        </select>
                    </label>
                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("agentManager.mode")}
                        </span>
                        <select
                            value={editing ? editingMode ?? "primary" : agentMode}
                            disabled={Boolean(editing)}
                            onChange={(event) =>
                                setAgentMode(
                                    event.target.value as NovaAgentMode,
                                )
                            }
                            className={inputClassName}
                        >
                            <option value="primary">
                                {t("agentManager.modePrimary")}
                            </option>
                            <option value="subagent">
                                {t("agentManager.modeSubagent")}
                            </option>
                        </select>
                        {!editing ? (
                            <span className="block text-[11px] text-muted-foreground">
                                {t("agentManager.modeHint")}
                            </span>
                        ) : null}
                    </label>
                    {isSubagent && !editing ? (
                        <label className="block space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("agentManager.posture")}
                            </span>
                            <select
                                value={posture}
                                onChange={(event) =>
                                    setPosture(
                                        event.target.value as NovaAgentPosture,
                                    )
                                }
                                className={inputClassName}
                            >
                                <option value="full">
                                    {t("agentManager.postureFull")}
                                </option>
                                <option value="read_only">
                                    {t("agentManager.postureReadOnly")}
                                </option>
                            </select>
                            <span className="block text-[11px] text-muted-foreground">
                                {t("agentManager.postureHint")}
                            </span>
                        </label>
                    ) : null}
                    {isSubagent ? (
                        <fieldset className="block space-y-1">
                            <legend className="text-xs font-medium text-foreground">
                                {t("agentManager.parents")}
                            </legend>
                            {primaryOptions.length === 0 ? (
                                <p className="text-[11px] text-muted-foreground">
                                    {t("agentManager.noPrimaryAgents")}
                                </p>
                            ) : (
                                <div className="max-h-32 space-y-1 overflow-y-auto rounded-md border p-2">
                                    {primaryOptions.map((agent) => {
                                        const checked = parentKeys.includes(
                                            agent.key,
                                        );
                                        return (
                                            <label
                                                key={agent.key}
                                                className="flex cursor-pointer items-center gap-2 text-xs"
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={checked}
                                                    onChange={() =>
                                                        toggleParent(
                                                            agent.key,
                                                        )
                                                    }
                                                />
                                                <span className="truncate">
                                                    {agent.name || agent.key}
                                                    <span className="ml-1 font-mono text-[11px] text-muted-foreground">
                                                        {agent.key}
                                                    </span>
                                                </span>
                                            </label>
                                        );
                                    })}
                                </div>
                            )}
                            <span className="block text-[11px] text-muted-foreground">
                                {t("agentManager.parentsHint")}
                            </span>
                        </fieldset>
                    ) : null}
                    {editing && editingMode === "subagent" ? (
                        <div className="block space-y-1">
                            <span className="text-xs font-medium text-foreground">
                                {t("agentManager.posture")}
                            </span>
                            <select
                                value={posture}
                                disabled
                                className={inputClassName}
                            >
                                <option value="full">
                                    {t("agentManager.postureFull")}
                                </option>
                                <option value="read_only">
                                    {t("agentManager.postureReadOnly")}
                                </option>
                            </select>
                            <span className="block text-[11px] text-muted-foreground">
                                {t("agentManager.postureReadonlyNote")}
                            </span>
                        </div>
                    ) : null}
                    {error ? (
                        <p className="text-xs text-destructive">{error}</p>
                    ) : null}
                </div>

                <DialogFooter>
                    <DialogClose asChild>
                        <Button type="button" size="sm" variant="outline">
                            {t("common.cancel")}
                        </Button>
                    </DialogClose>
                    <Button
                        type="button"
                        size="sm"
                        disabled={saving}
                        onClick={() => void handleSave()}
                    >
                        {editing
                            ? t("modelSelector.saveChanges")
                            : t("agentManager.create")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
