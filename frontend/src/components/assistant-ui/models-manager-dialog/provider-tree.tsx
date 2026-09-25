import { useTranslation } from "react-i18next";
import {
    ChevronRightIcon,
    PencilIcon,
    PlusIcon,
    Trash2Icon,
} from "lucide-react";

import { HighlightedText } from "../../sidebar/highlight-text";
import { Button } from "../../ui/button";
import { cn } from "../../../lib/utils";
import type { NovaModelRecord, NovaProviderRecord } from "./types";

export type ProviderGroup = {
    provider: NovaProviderRecord;
    models: NovaModelRecord[];
    /** True when the group is open only because a child model matched the query. */
    forcedOpen: boolean;
};

type ProviderTreeProps = {
    groups: ProviderGroup[];
    isOpen: (providerKey: string) => boolean;
    query: string;
    busy: boolean;
    onToggle: (providerKey: string) => void;
    onEditProvider: (provider: NovaProviderRecord) => void;
    onDeleteProvider: (provider: NovaProviderRecord) => void;
    onAddModel: (providerKey: string) => void;
    onEditModel: (model: NovaModelRecord) => void;
    onDeleteModel: (model: NovaModelRecord) => void;
};

/**
 * One bordered column of providers, each expanding to its models. Flat
 * dividers between groups keep it a single surface rather than nested cards.
 */
export function ProviderTree({
    groups,
    isOpen,
    query,
    busy,
    onToggle,
    onEditProvider,
    onDeleteProvider,
    onAddModel,
    onEditModel,
    onDeleteModel,
}: ProviderTreeProps) {
    const { t } = useTranslation();

    if (groups.length === 0) {
        return (
            <div className="flex min-h-0 flex-1 items-center justify-center rounded-xl border border-dashed text-sm text-muted-foreground">
                {query
                    ? t("modelSelector.noMatchingProviders")
                    : t("modelSelector.noProvidersHint")}
            </div>
        );
    }

    return (
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto rounded-xl border">
            {groups.map((group, groupIndex) => {
                const { provider, models, forcedOpen } = group;
                const open = isOpen(provider.key);
                return (
                    <div
                        key={provider.key}
                        className={cn(groupIndex > 0 && "border-t")}
                    >
                        <div className="flex items-center gap-1 px-2 py-1.5 hover:bg-muted/40">
                            <button
                                type="button"
                                onClick={() => onToggle(provider.key)}
                                aria-expanded={open}
                                className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 text-left"
                            >
                                <ChevronRightIcon
                                    className={cn(
                                        "size-4 shrink-0 text-muted-foreground transition-transform",
                                        open && "rotate-90",
                                    )}
                                />
                                <span className="min-w-0 truncate text-[13.5px] font-medium">
                                    <HighlightedText
                                        text={provider.name}
                                        query={query}
                                    />
                                </span>
                                <span className="shrink-0 text-[11px] text-muted-foreground">
                                    {t("modelSelector.modelCount", {
                                        count: models.length,
                                    })}
                                </span>
                            </button>
                            <Button
                                type="button"
                                size="icon-xs"
                                variant="ghost"
                                className="shrink-0 text-muted-foreground hover:text-foreground"
                                title={t("modelSelector.editProvider")}
                                aria-label={t("modelSelector.editProvider")}
                                onClick={() => onEditProvider(provider)}
                            >
                                <PencilIcon className="size-3.5" />
                            </Button>
                            <Button
                                type="button"
                                size="icon-xs"
                                variant="ghost"
                                className="shrink-0 text-muted-foreground hover:text-destructive"
                                title={t("modelSelector.deleteProvider")}
                                aria-label={t("modelSelector.deleteProvider")}
                                onClick={() => onDeleteProvider(provider)}
                            >
                                <Trash2Icon className="size-3.5" />
                            </Button>
                        </div>
                        {open ? (
                            <div
                                className={cn(
                                    "border-t bg-muted/20 px-2 py-1",
                                    forcedOpen && "bg-[#FCEFC7]/40",
                                )}
                            >
                                {models.map((model) => {
                                    const displayName =
                                        model.label || model.model;
                                    return (
                                        <div
                                            key={model.id}
                                            className="flex items-center gap-1 py-1 pl-7 pr-1 hover:bg-muted/40"
                                        >
                                            <span className="flex min-w-0 flex-1 flex-col">
                                                <span className="truncate text-[13px]">
                                                    <HighlightedText
                                                        text={displayName}
                                                        query={query}
                                                    />
                                                </span>
                                                <span className="truncate font-mono text-[11px] text-muted-foreground">
                                                    <HighlightedText
                                                        text={model.model}
                                                        query={query}
                                                    />
                                                </span>
                                            </span>
                                            <Button
                                                type="button"
                                                size="icon-xs"
                                                variant="ghost"
                                                className="shrink-0 text-muted-foreground hover:text-foreground"
                                                title={t(
                                                    "modelSelector.editModel",
                                                )}
                                                aria-label={t(
                                                    "modelSelector.editModel",
                                                )}
                                                onClick={() =>
                                                    onEditModel(model)
                                                }
                                            >
                                                <PencilIcon className="size-3.5" />
                                            </Button>
                                            <Button
                                                type="button"
                                                size="icon-xs"
                                                variant="ghost"
                                                className="shrink-0 text-muted-foreground hover:text-destructive"
                                                title={t(
                                                    "modelSelector.deleteModel",
                                                )}
                                                aria-label={t(
                                                    "modelSelector.deleteModel",
                                                )}
                                                disabled={busy}
                                                onClick={() =>
                                                    onDeleteModel(model)
                                                }
                                            >
                                                <Trash2Icon className="size-3.5" />
                                            </Button>
                                        </div>
                                    );
                                })}
                                <div className="py-1 pl-7">
                                    <Button
                                        type="button"
                                        size="sm"
                                        variant="ghost"
                                        className="h-7 text-[12.5px] text-muted-foreground hover:text-foreground"
                                        onClick={() =>
                                            onAddModel(provider.key)
                                        }
                                    >
                                        <PlusIcon className="size-3.5" />
                                        {t("modelSelector.addModel")}
                                    </Button>
                                </div>
                            </div>
                        ) : null}
                    </div>
                );
            })}
        </div>
    );
}
