import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "../../ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../../ui/dialog";
import { ModelsPanel } from "./models-panel";
import { ProviderPanel } from "./provider-panel";
import type {
    ModelsManagerDialogProps,
    NovaModelRecord,
} from "./types";

export function ModelsManagerDialog({
    open,
    onOpenChange,
    providers,
    models,
    onModelsUpdated,
    onProvidersRefresh,
    onStatusChange,
}: ModelsManagerDialogProps) {
    const { t } = useTranslation();
    const [rawSelectedKey, setRawSelectedKey] = useState<string | null>(null);

    const selectedProviderKey =
        rawSelectedKey &&
        providers.some((provider) => provider.key === rawSelectedKey)
            ? rawSelectedKey
            : (providers[0]?.key ?? null);
    const selectedProvider = providers.find(
        (provider) => provider.key === selectedProviderKey,
    );
    const selectedModels = models.filter(
        (model) => model.provider === selectedProviderKey,
    );

    async function refreshAfterMutation(nextModels: NovaModelRecord[]) {
        onModelsUpdated(nextModels);
        await onProvidersRefresh();
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-3xl">
                <DialogHeader>
                    <DialogTitle>{t("modelSelector.managerTitle")}</DialogTitle>
                    <DialogDescription>
                        {t("modelSelector.managerDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex max-h-[60vh] min-h-[320px] gap-4 overflow-hidden">
                    <ProviderPanel
                        providers={providers}
                        models={models}
                        selectedKey={selectedProviderKey}
                        onSelectKey={setRawSelectedKey}
                        onMutated={refreshAfterMutation}
                        onStatusChange={onStatusChange}
                    />

                    <div className="min-w-0 flex-1 overflow-y-auto">
                        {!selectedProvider ? (
                            <p className="py-10 text-center text-sm text-muted-foreground">
                                {providers.length === 0
                                    ? t("modelSelector.noProvidersHint")
                                    : t("modelSelector.selectProviderHint")}
                            </p>
                        ) : (
                            <ModelsPanel
                                key={selectedProvider.key}
                                provider={selectedProvider}
                                models={selectedModels}
                                onMutated={refreshAfterMutation}
                                onStatusChange={onStatusChange}
                                onProviderDeleted={() =>
                                    setRawSelectedKey(null)
                                }
                            />
                        )}
                    </div>
                </div>

                <DialogFooter>
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        {t("common.close")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
