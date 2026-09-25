import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { PlusIcon, SearchIcon } from "lucide-react";

import { deleteModel, deleteProvider } from "../../../lib/nova-api";
import { Button } from "../../ui/button";
import { ConfirmDialog } from "../../ui/confirm-dialog";
import { ModelDialog } from "./model-dialog";
import { ProviderDialog } from "./provider-dialog";
import { ProviderTree, type ProviderGroup } from "./provider-tree";
import type {
    NovaModelRecord,
    NovaProviderRecord,
} from "./types";

export interface ModelsManagerContentProps {
    providers: NovaProviderRecord[];
    models: NovaModelRecord[];
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onStatusChange: (message: string | null) => void;
}

function matches(haystack: string, needle: string): boolean {
    return haystack.toLocaleLowerCase().includes(needle);
}

export function ModelsManagerContent({
    providers,
    models,
    onModelsUpdated,
    onProvidersRefresh,
    onStatusChange,
}: ModelsManagerContentProps) {
    const { t } = useTranslation();
    const [query, setQuery] = useState("");
    const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
    const [busy, setBusy] = useState(false);
    const [creatingProvider, setCreatingProvider] = useState(false);
    const [editingProvider, setEditingProvider] =
        useState<NovaProviderRecord | null>(null);
    const [creatingModelFor, setCreatingModelFor] = useState<string | null>(
        null,
    );
    const [editingModel, setEditingModel] = useState<NovaModelRecord | null>(
        null,
    );
    const [deletingProvider, setDeletingProvider] =
        useState<NovaProviderRecord | null>(null);
    const [deletingModel, setDeletingModel] =
        useState<NovaModelRecord | null>(null);

    const needle = query.trim().toLocaleLowerCase();

    const groups = useMemo<ProviderGroup[]>(() => {
        return providers.flatMap((provider) => {
            const providerModels = models.filter(
                (model) => model.provider === provider.key,
            );
            if (!needle) {
                return [{ provider, models: providerModels, forcedOpen: false }];
            }
            const providerHit = matches(provider.name, needle);
            const modelHits = providerModels.filter(
                (model) =>
                    matches(model.label, needle) || matches(model.model, needle),
            );
            if (!providerHit && modelHits.length === 0) {
                return [];
            }
            return [
                {
                    provider,
                    models: providerHit ? providerModels : modelHits,
                    forcedOpen: !providerHit,
                },
            ];
        });
    }, [providers, models, needle]);

    // A group whose models matched must reveal them even while collapsed.
    const forcedOpenKeys = useMemo(
        () =>
            new Set(
                groups.filter((group) => group.forcedOpen).map((g) => g.provider.key),
            ),
        [groups],
    );

    function isOpen(providerKey: string): boolean {
        return expanded.has(providerKey) || forcedOpenKeys.has(providerKey);
    }

    function toggleProvider(providerKey: string) {
        setExpanded((current) => {
            const next = new Set(current);
            if (next.has(providerKey)) {
                next.delete(providerKey);
            } else {
                next.add(providerKey);
            }
            return next;
        });
    }

    async function refreshAfterMutation(nextModels: NovaModelRecord[]) {
        onModelsUpdated(nextModels);
        await onProvidersRefresh();
    }

    async function handleDeleteProvider() {
        if (!deletingProvider) {
            return;
        }
        onStatusChange(null);
        setBusy(true);
        try {
            const nextModels = await deleteProvider(deletingProvider.key);
            await refreshAfterMutation(nextModels);
            setDeletingProvider(null);
            setExpanded((current) => {
                const next = new Set(current);
                next.delete(deletingProvider.key);
                return next;
            });
        } catch (error) {
            onStatusChange(
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            setBusy(false);
        }
    }

    async function handleDeleteModel() {
        if (!deletingModel) {
            return;
        }
        onStatusChange(null);
        setBusy(true);
        try {
            const nextModels = await deleteModel(
                deletingModel.provider,
                deletingModel.model,
            );
            await refreshAfterMutation(nextModels);
            setDeletingModel(null);
        } catch (error) {
            onStatusChange(
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="flex h-full min-h-0 min-w-0 flex-col gap-3">
            <div className="flex shrink-0 items-center gap-2">
                <div className="relative min-w-0 flex-1">
                    <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder={t("modelSelector.searchProviders")}
                        className="h-9 w-full rounded-lg border bg-background pr-3 pl-8 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
                    />
                </div>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    onClick={() => setCreatingProvider(true)}
                >
                    <PlusIcon className="size-3.5" />
                    {t("modelSelector.addProvider")}
                </Button>
            </div>

            <ProviderTree
                groups={groups}
                isOpen={isOpen}
                query={query.trim()}
                busy={busy}
                onToggle={toggleProvider}
                onEditProvider={setEditingProvider}
                onDeleteProvider={setDeletingProvider}
                onAddModel={setCreatingModelFor}
                onEditModel={setEditingModel}
                onDeleteModel={setDeletingModel}
            />

            {creatingProvider ? (
                <ProviderDialog
                    key="new-provider"
                    open
                    onOpenChange={setCreatingProvider}
                    onMutated={refreshAfterMutation}
                    onStatusChange={onStatusChange}
                    onCreated={(key) => setExpanded((c) => new Set(c).add(key))}
                />
            ) : null}
            {editingProvider ? (
                <ProviderDialog
                    key={`edit-provider-${editingProvider.key}`}
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setEditingProvider(null);
                        }
                    }}
                    provider={editingProvider}
                    onMutated={refreshAfterMutation}
                    onStatusChange={onStatusChange}
                    onDeleted={() => setEditingProvider(null)}
                />
            ) : null}
            {creatingModelFor ? (
                <ModelDialog
                    key={`new-model-${creatingModelFor}`}
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setCreatingModelFor(null);
                        }
                    }}
                    providerKey={creatingModelFor}
                    onMutated={refreshAfterMutation}
                    onStatusChange={onStatusChange}
                />
            ) : null}
            {editingModel ? (
                <ModelDialog
                    key={`edit-model-${editingModel.id}`}
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setEditingModel(null);
                        }
                    }}
                    providerKey={editingModel.provider}
                    model={editingModel}
                    onMutated={refreshAfterMutation}
                    onStatusChange={onStatusChange}
                />
            ) : null}
            {deletingProvider ? (
                <ConfirmDialog
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setDeletingProvider(null);
                        }
                    }}
                    title={t("modelSelector.deleteProvider")}
                    description={t("modelSelector.confirmDeleteProvider")}
                    confirmLabel={t("modelSelector.delete")}
                    onConfirm={() => void handleDeleteProvider()}
                />
            ) : null}
            {deletingModel ? (
                <ConfirmDialog
                    open
                    onOpenChange={(open) => {
                        if (!open) {
                            setDeletingModel(null);
                        }
                    }}
                    title={t("modelSelector.deleteModel")}
                    description={t("modelSelector.confirmDeleteModel")}
                    confirmLabel={t("modelSelector.delete")}
                    onConfirm={() => void handleDeleteModel()}
                />
            ) : null}
        </div>
    );
}
