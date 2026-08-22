import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { listDirectory } from "@/lib/nova-api";
import type { NovaDirectoryListing } from "@/types/nova";
import { CornerLeftUpIcon, FolderIcon, HomeIcon, RotateCcwIcon } from "lucide-react";
import { type FC, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

type WorkspacePickerProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    initialPath?: string | null;
    onSelect: (path: string | null) => void;
    allowClear?: boolean;
};

export const WorkspacePicker: FC<WorkspacePickerProps> = ({
    open,
    onOpenChange,
    initialPath,
    onSelect,
    allowClear = true,
}) => {
    const { t } = useTranslation();
    const [listing, setListing] = useState<NovaDirectoryListing | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async (path?: string | null) => {
        setLoading(true);
        setError(null);
        try {
            setListing(await listDirectory(path ?? undefined));
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!open) {
            return;
        }
        let cancelled = false;
        void (async () => {
            const result = await listDirectory(initialPath ?? undefined).catch(
                (err: unknown) =>
                    err instanceof Error ? err : new Error(String(err)),
            );
            if (cancelled) {
                return;
            }
            if (result instanceof Error) {
                setError(result.message);
            } else {
                setListing(result);
                setError(null);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [open, initialPath]);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>{t("workspace.pickerTitle")}</DialogTitle>
                    <DialogDescription>
                        {t("workspace.pickerDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex items-center gap-2">
                    <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        aria-label={t("workspace.home")}
                        onClick={() => void load(null)}
                    >
                        <HomeIcon className="size-4" />
                    </Button>
                    <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        aria-label={t("workspace.parent")}
                        disabled={!listing?.parent}
                        onClick={() => void load(listing?.parent)}
                    >
                        <CornerLeftUpIcon className="size-4" />
                    </Button>
                    <div className="min-w-0 flex-1 truncate rounded-md border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
                        {listing?.path ?? "…"}
                    </div>
                </div>

                <div className="h-64 overflow-y-auto rounded-md border">
                    {loading && (
                        <p className="px-3 py-2 text-sm text-muted-foreground">
                            {t("common.loading")}
                        </p>
                    )}
                    {!loading && error && (
                        <p className="px-3 py-2 text-sm text-destructive">
                            {error}
                        </p>
                    )}
                    {!loading && !error && listing?.entries.length === 0 && (
                        <p className="px-3 py-2 text-sm text-muted-foreground">
                            {t("workspace.emptyDir")}
                        </p>
                    )}
                    {!loading &&
                        !error &&
                        listing?.entries.map((entry) => (
                            <button
                                key={entry.path}
                                type="button"
                                onClick={() => void load(entry.path)}
                                className="flex w-full items-center gap-2 px-3 py-1.5 text-start text-sm hover:bg-muted"
                            >
                                <FolderIcon className="size-4 shrink-0 text-muted-foreground" />
                                <span className="min-w-0 flex-1 truncate">
                                    {entry.name}
                                </span>
                            </button>
                        ))}
                </div>

                <DialogFooter className="gap-2 sm:justify-between">
                    {allowClear ? (
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={() => {
                                onSelect(null);
                                onOpenChange(false);
                            }}
                        >
                            <RotateCcwIcon className="size-4" />
                            {t("workspace.useDefault")}
                        </Button>
                    ) : (
                        <span />
                    )}
                    <div className="flex gap-2">
                        <DialogClose asChild>
                            <Button type="button" variant="outline">
                                {t("common.cancel")}
                            </Button>
                        </DialogClose>
                        <Button
                            type="button"
                            disabled={!listing?.path || loading}
                            onClick={() => {
                                if (listing?.path) {
                                    onSelect(listing.path);
                                    onOpenChange(false);
                                }
                            }}
                        >
                            {t("workspace.selectThisFolder")}
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
