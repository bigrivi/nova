import { useState } from "react";
import { useTranslation } from "react-i18next";

import { createModel, updateModel } from "../../../lib/nova-api";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../../ui/dialog";
import type { NovaModelRecord } from "./types";
import { inputClassName } from "./types";

type ModelDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    providerKey: string;
    /** undefined = create mode, otherwise edit mode for this model. */
    model?: NovaModelRecord;
    onMutated: (nextModels: NovaModelRecord[]) => Promise<void>;
    onStatusChange: (message: string | null) => void;
};

export function ModelDialog({
    open,
    onOpenChange,
    providerKey,
    model,
    onMutated,
    onStatusChange,
}: ModelDialogProps) {
    const { t } = useTranslation();
    const isEdit = model !== undefined;
    const [modelKey, setModelKey] = useState(model?.model ?? "");
    const [label, setLabel] = useState(model?.label ?? "");
    const [tools, setTools] = useState(model?.tools ?? true);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    async function handleCreate() {
        setError(null);
        onStatusChange(null);
        setSaving(true);
        try {
            const nextModels = await createModel({
                provider: providerKey,
                model: modelKey,
                label,
                tools,
            });
            await onMutated(nextModels);
            onOpenChange(false);
        } catch (error) {
            const message =
                error instanceof Error ? error.message : String(error);
            setError(message);
            onStatusChange(message);
        } finally {
            setSaving(false);
        }
    }

    async function handleUpdate() {
        if (!model) {
            return;
        }
        setError(null);
        onStatusChange(null);
        setSaving(true);
        try {
            const nextModels = await updateModel(model.provider, model.model, {
                label,
                tools,
            });
            await onMutated(nextModels);
            onOpenChange(false);
        } catch (error) {
            const message =
                error instanceof Error ? error.message : String(error);
            setError(message);
            onStatusChange(message);
        } finally {
            setSaving(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                        {isEdit
                            ? t("modelSelector.editModelDialogTitle")
                            : t("modelSelector.addModelDialogTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {isEdit
                            ? t("modelSelector.editModelDialogDescription")
                            : t("modelSelector.addModelDialogDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-3">
                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("modelSelector.modelKey")}
                        </span>
                        <input
                            value={isEdit ? model.model : modelKey}
                            onChange={(event) =>
                                setModelKey(event.target.value)
                            }
                            disabled={isEdit}
                            className={cn(
                                inputClassName,
                                isEdit && "opacity-60",
                            )}
                            placeholder={t(
                                "modelSelector.modelKeyPlaceholder",
                            )}
                        />
                    </label>
                    <label className="block space-y-1">
                        <span className="text-xs font-medium text-foreground">
                            {t("modelSelector.label")}
                        </span>
                        <input
                            value={label}
                            onChange={(event) => setLabel(event.target.value)}
                            className={inputClassName}
                            placeholder={t("modelSelector.labelPlaceholder")}
                        />
                    </label>
                    <label className="flex items-center gap-2 rounded-lg border bg-background px-3 py-2">
                        <input
                            type="checkbox"
                            checked={tools}
                            onChange={(event) =>
                                setTools(event.target.checked)
                            }
                            className="size-4 rounded border"
                        />
                        <span className="text-sm text-foreground">
                            {t("modelSelector.enableTools")}
                        </span>
                    </label>
                    {error ? (
                        <p className="text-xs text-destructive">{error}</p>
                    ) : null}
                </div>

                <DialogFooter>
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        {t("common.cancel")}
                    </Button>
                    <Button
                        type="button"
                        size="sm"
                        disabled={saving}
                        onClick={() =>
                            void (isEdit ? handleUpdate() : handleCreate())
                        }
                    >
                        {isEdit
                            ? t("modelSelector.saveChanges")
                            : t("modelSelector.saveModel")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
