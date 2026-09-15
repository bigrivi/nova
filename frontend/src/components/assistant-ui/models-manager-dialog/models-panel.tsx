import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PencilIcon, Trash2Icon } from "lucide-react";

import { deleteModel, updateModel } from "../../../lib/nova-api";
import { Button } from "../../ui/button";
import { ConfirmDialog } from "../../ui/confirm-dialog";
import { ModelDialog } from "./model-dialog";
import { ProviderDialog } from "./provider-dialog";
import type { NovaModelRecord, NovaProviderRecord } from "./types";
import { inputClassName } from "./types";

type ModelsPanelProps = {
    provider: NovaProviderRecord;
    models: NovaModelRecord[];
    onMutated: (nextModels: NovaModelRecord[]) => Promise<void>;
    onStatusChange: (message: string | null) => void;
    onProviderDeleted: () => void;
};

export function ModelsPanel({
    provider,
    models,
    onMutated,
    onStatusChange,
    onProviderDeleted,
}: ModelsPanelProps) {
    const { t } = useTranslation();
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [modelError, setModelError] = useState<string | null>(null);
    const [showModelDialog, setShowModelDialog] = useState(false);
    const [showProviderDialog, setShowProviderDialog] = useState(false);
    const [editingModelId, setEditingModelId] = useState<string | null>(null);
    const [confirmingDelete, setConfirmingDelete] =
        useState<NovaModelRecord | null>(null);
    const [editLabel, setEditLabel] = useState("");
    const [editTools, setEditTools] = useState(true);

    function startModelEdit(model: NovaModelRecord) {
        setEditingModelId(model.id);
        setEditLabel(model.label);
        setEditTools(model.tools);
        setModelError(null);
    }

    async function handleModelUpdate(model: NovaModelRecord) {
        onStatusChange(null);
        setIsSubmitting(true);
        try {
            const nextModels = await updateModel(model.provider, model.model, {
                label: editLabel,
                tools: editTools,
            });
            await onMutated(nextModels);
            setEditingModelId(null);
        } catch (error) {
            const message =
                error instanceof Error ? error.message : String(error);
            setModelError(message);
            onStatusChange(message);
        } finally {
            setIsSubmitting(false);
        }
    }

    async function handleModelDelete(model: NovaModelRecord) {
        onStatusChange(null);
        setIsSubmitting(true);
        try {
            const nextModels = await deleteModel(model.provider, model.model);
            await onMutated(nextModels);
            if (editingModelId === model.id) {
                setEditingModelId(null);
            }
        } catch (error) {
            const message =
                error instanceof Error ? error.message : String(error);
            setModelError(message);
            onStatusChange(message);
        } finally {
            setIsSubmitting(false);
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2">
                <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">
                        {provider.name}
                    </p>
                    <p className="truncate font-mono text-xs text-muted-foreground">
                        {provider.key}
                    </p>
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => setShowProviderDialog(true)}
                >
                    {t("modelSelector.edit")}
                </Button>
            </div>

            <div>
                <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("modelSelector.models")} ({models.length})
                    </p>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setShowModelDialog(true)}
                    >
                        {t("modelSelector.newModel")}
                    </Button>
                </div>

                {models.length === 0 ? (
                    <p className="rounded-lg border border-dashed py-6 text-center text-sm text-muted-foreground">
                        {t("modelSelector.noModelsHint")}
                    </p>
                ) : (
                    <div className="overflow-hidden rounded-lg border">
                        <div className="grid grid-cols-[minmax(0,1fr)_64px_72px] items-center gap-2 border-b bg-muted/40 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                            <span>{t("modelSelector.modelColumn")}</span>
                            <span className="text-center">
                                {t("modelSelector.toolsColumn")}
                            </span>
                            <span className="text-center">
                                {t("modelSelector.actionsColumn")}
                            </span>
                        </div>
                        {models.map((model) => {
                            const isEditing = editingModelId === model.id;
                            return (
                                <div
                                    key={model.id}
                                    className="border-b px-3 py-2 last:border-b-0"
                                >
                                    {isEditing ? (
                                        <div className="space-y-2">
                                            <input
                                                value={editLabel}
                                                onChange={(event) =>
                                                    setEditLabel(
                                                        event.target.value,
                                                    )
                                                }
                                                className={inputClassName}
                                                placeholder={t(
                                                    "modelSelector.labelPlaceholder",
                                                )}
                                            />
                                            <label className="flex items-center gap-2 text-sm">
                                                <input
                                                    type="checkbox"
                                                    checked={editTools}
                                                    onChange={(event) =>
                                                        setEditTools(
                                                            event.target.checked,
                                                        )
                                                    }
                                                    className="size-4 rounded border"
                                                />
                                                {t("modelSelector.enableTools")}
                                            </label>
                                            <div className="flex gap-2">
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    disabled={isSubmitting}
                                                    onClick={() =>
                                                        void handleModelUpdate(
                                                            model,
                                                        )
                                                    }
                                                >
                                                    {t(
                                                        "modelSelector.saveChanges",
                                                    )}
                                                </Button>
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() =>
                                                        setEditingModelId(null)
                                                    }
                                                >
                                                    {t("common.cancel")}
                                                </Button>
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="grid grid-cols-[minmax(0,1fr)_64px_72px] items-center gap-2">
                                            <div className="min-w-0">
                                                <p className="truncate text-sm font-medium">
                                                    {model.label}
                                                </p>
                                                <p className="truncate text-xs text-muted-foreground">
                                                    {model.model}
                                                </p>
                                            </div>
                                            <span className="text-center text-xs text-muted-foreground">
                                                {model.tools
                                                    ? t(
                                                          "modelSelector.toolsOn",
                                                      )
                                                    : t(
                                                          "modelSelector.toolsOff",
                                                      )}
                                            </span>
                                            <div className="flex justify-center gap-1">
                                                <Button
                                                    type="button"
                                                    size="icon-xs"
                                                    variant="ghost"
                                                    title={t(
                                                        "modelSelector.edit",
                                                    )}
                                                    aria-label={t(
                                                        "modelSelector.edit",
                                                    )}
                                                    onClick={() =>
                                                        startModelEdit(model)
                                                    }
                                                >
                                                    <PencilIcon className="size-3.5" />
                                                </Button>
                                                <Button
                                                    type="button"
                                                    size="icon-xs"
                                                    variant="ghost"
                                                    className="text-destructive hover:text-destructive"
                                                    title={t(
                                                        "modelSelector.delete",
                                                    )}
                                                    aria-label={t(
                                                        "modelSelector.delete",
                                                    )}
                                                    disabled={isSubmitting}
                                                    onClick={() =>
                                                        setConfirmingDelete(
                                                            model,
                                                        )
                                                    }
                                                >
                                                    <Trash2Icon className="size-3.5" />
                                                </Button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}
                {modelError ? (
                    <p className="mt-2 text-xs text-destructive">{modelError}</p>
                ) : null}
            </div>

            {showProviderDialog ? (
                <ProviderDialog
                    key={provider.key}
                    open={showProviderDialog}
                    onOpenChange={setShowProviderDialog}
                    provider={provider}
                    onMutated={onMutated}
                    onStatusChange={onStatusChange}
                    onDeleted={onProviderDeleted}
                />
            ) : null}
            {showModelDialog ? (
                <ModelDialog
                    key={`${provider.key}-new-model`}
                    open={showModelDialog}
                    onOpenChange={setShowModelDialog}
                    providerKey={provider.key}
                    onMutated={onMutated}
                    onStatusChange={onStatusChange}
                />
            ) : null}
            {confirmingDelete ? (
                <ConfirmDialog
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setConfirmingDelete(null);
                        }
                    }}
                    title={t("modelSelector.deleteModel")}
                    description={t("modelSelector.confirmDeleteModel")}
                    confirmLabel={t("modelSelector.delete")}
                    onConfirm={() =>
                        void handleModelDelete(confirmingDelete)
                    }
                />
            ) : null}
        </div>
    );
}
