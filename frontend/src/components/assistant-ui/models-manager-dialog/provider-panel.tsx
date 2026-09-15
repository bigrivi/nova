import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2Icon } from "lucide-react";

import { deleteProvider } from "../../../lib/nova-api";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui/button";
import { ConfirmDialog } from "../../ui/confirm-dialog";
import { ProviderDialog } from "./provider-dialog";
import type { NovaModelRecord, NovaProviderRecord } from "./types";

type ProviderPanelProps = {
    providers: NovaProviderRecord[];
    models: NovaModelRecord[];
    selectedKey: string | null;
    onSelectKey: (key: string) => void;
    onMutated: (nextModels: NovaModelRecord[]) => Promise<void>;
    onStatusChange: (message: string | null) => void;
};

export function ProviderPanel({
    providers,
    models,
    selectedKey,
    onSelectKey,
    onMutated,
    onStatusChange,
}: ProviderPanelProps) {
    const { t } = useTranslation();
    const [showDialog, setShowDialog] = useState(false);
    const [confirmingDeleteKey, setConfirmingDeleteKey] = useState<
        string | null
    >(null);
    const [deleting, setDeleting] = useState(false);

    function countModels(providerKey: string): number {
        return models.filter((model) => model.provider === providerKey).length;
    }

    async function handleDelete(key: string) {
        onStatusChange(null);
        setDeleting(true);
        try {
            const nextModels = await deleteProvider(key);
            await onMutated(nextModels);
        } catch (error) {
            const message =
                error instanceof Error ? error.message : String(error);
            onStatusChange(message);
        } finally {
            setDeleting(false);
        }
    }

    return (
        <div className="flex w-52 shrink-0 flex-col gap-1 overflow-y-auto rounded-lg border bg-muted/20 p-2">
            <p className="px-1 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("modelSelector.providers")}
            </p>
            {providers.length === 0 ? (
                <p className="px-1 py-3 text-xs text-muted-foreground">
                    {t("modelSelector.noProvidersHint")}
                </p>
            ) : (
                providers.map((provider) => (
                    <div
                        key={provider.key}
                        className={cn(
                            "group flex items-center gap-1 rounded-md border px-1 py-0.5 hover:bg-muted/60",
                            provider.key === selectedKey
                                ? "border-primary/50 bg-muted font-semibold"
                                : "border-transparent",
                        )}
                    >
                        <button
                            type="button"
                            onClick={() => onSelectKey(provider.key)}
                            className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded px-1 py-1 text-left text-[13px] text-foreground"
                        >
                            <span className="min-w-0 truncate">
                                {provider.name}
                            </span>
                            <span className="shrink-0 text-[11px] text-muted-foreground">
                                {countModels(provider.key)}
                            </span>
                        </button>
                        <Button
                            type="button"
                            size="icon-xs"
                            variant="ghost"
                            className="shrink-0 text-muted-foreground opacity-0 hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
                            title={t("modelSelector.deleteProvider")}
                            aria-label={t("modelSelector.deleteProvider")}
                            disabled={deleting}
                            onClick={() =>
                                setConfirmingDeleteKey(provider.key)
                            }
                        >
                            <Trash2Icon className="size-3.5" />
                        </Button>
                    </div>
                ))
            )}
            <Button
                type="button"
                size="sm"
                variant="outline"
                className="mt-2"
                onClick={() => setShowDialog(true)}
            >
                {t("modelSelector.newProvider")}
            </Button>
            {showDialog ? (
                <ProviderDialog
                    key="new-provider"
                    open={showDialog}
                    onOpenChange={setShowDialog}
                    onMutated={onMutated}
                    onStatusChange={onStatusChange}
                    onCreated={onSelectKey}
                />
            ) : null}
            {confirmingDeleteKey ? (
                <ConfirmDialog
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setConfirmingDeleteKey(null);
                        }
                    }}
                    title={t("modelSelector.deleteProvider")}
                    description={t("modelSelector.confirmDeleteProvider")}
                    confirmLabel={t("modelSelector.delete")}
                    onConfirm={() => void handleDelete(confirmingDeleteKey)}
                />
            ) : null}
        </div>
    );
}
