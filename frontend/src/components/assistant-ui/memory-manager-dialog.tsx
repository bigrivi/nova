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
import { deleteMemory, listMemories } from "@/lib/nova-api";
import type { NovaMemoryRecord } from "@/types/nova";
import { Trash2Icon } from "lucide-react";
import { useEffect, useState, type FC } from "react";
import { useTranslation } from "react-i18next";

type MemoryManagerDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
};

const SCOPE_ORDER: NovaMemoryRecord["scope"][] = ["user", "project", "session"];

const SCOPE_LABEL_KEY: Record<NovaMemoryRecord["scope"], string> = {
    user: "memory.scope.user",
    project: "memory.scope.project",
    session: "memory.scope.session",
};

const TYPE_LABEL_KEY: Record<NovaMemoryRecord["memory_type"], string> = {
    fact: "memory.type.fact",
    preference: "memory.type.preference",
    decision: "memory.type.decision",
    context: "memory.type.context",
};

export const MemoryManagerDialog: FC<MemoryManagerDialogProps> = ({
    open,
    onOpenChange,
}) => {
    const { t } = useTranslation();
    const [memories, setMemories] = useState<NovaMemoryRecord[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [memoryToDelete, setMemoryToDelete] =
        useState<NovaMemoryRecord | null>(null);
    const [deleting, setDeleting] = useState(false);
    const [deleteError, setDeleteError] = useState<string | null>(null);

    useEffect(() => {
        if (!open) {
            return;
        }
        let cancelled = false;
        listMemories()
            .then((items) => {
                if (!cancelled) {
                    setMemories(
                        [...items].sort((a, b) => b.updated_at - a.updated_at),
                    );
                    setLoadError(null);
                }
            })
            .catch((error) => {
                if (!cancelled) {
                    setLoadError(
                        error instanceof Error ? error.message : String(error),
                    );
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false);
                }
            });
        return () => {
            cancelled = true;
        };
    }, [open]);

    const handleConfirmDelete = async () => {
        if (!memoryToDelete) {
            return;
        }
        setDeleting(true);
        setDeleteError(null);
        try {
            await deleteMemory(memoryToDelete.id);
            setMemories((previous) =>
                previous.filter((memory) => memory.id !== memoryToDelete.id),
            );
            setMemoryToDelete(null);
        } catch (error) {
            setDeleteError(
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            setDeleting(false);
        }
    };

    const formatTime = (timestamp: number) =>
        new Date(timestamp).toLocaleString();

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="sm:max-w-lg">
                    <DialogHeader>
                        <DialogTitle>{t("memory.manage")}</DialogTitle>
                        <DialogDescription>
                            {t("memory.manageDescription")}
                        </DialogDescription>
                    </DialogHeader>
                    <div className="max-h-[60vh] overflow-y-auto pr-1">
                        {loading && (
                            <p className="py-6 text-center text-sm text-muted-foreground">
                                {t("threadList.loadingThreads")}
                            </p>
                        )}
                        {!loading && loadError && (
                            <p className="py-6 text-center text-sm text-destructive">
                                {loadError}
                            </p>
                        )}
                        {!loading && !loadError && memories.length === 0 && (
                            <p className="py-6 text-center text-sm text-muted-foreground">
                                {t("memory.empty")}
                            </p>
                        )}
                        {!loading &&
                            !loadError &&
                            SCOPE_ORDER.map((scope) => {
                                const group = memories.filter(
                                    (memory) => memory.scope === scope,
                                );
                                if (group.length === 0) {
                                    return null;
                                }
                                return (
                                    <div key={scope} className="mb-4 last:mb-0">
                                        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                            {t(SCOPE_LABEL_KEY[scope])} (
                                            {group.length})
                                        </h3>
                                        <div className="flex flex-col gap-2">
                                            {group.map((memory) => (
                                                <div
                                                    key={memory.id}
                                                    className="rounded-lg border bg-card p-3"
                                                >
                                                    <div className="flex items-start justify-between gap-2">
                                                        <div className="min-w-0 flex-1">
                                                            <div className="flex flex-wrap items-center gap-1.5">
                                                                <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                                                                    {t(
                                                                        TYPE_LABEL_KEY[
                                                                            memory
                                                                                .memory_type
                                                                        ],
                                                                    )}
                                                                </span>
                                                                <span className="truncate text-sm font-medium">
                                                                    {memory.key}
                                                                </span>
                                                                {memory.tags.map(
                                                                    (tag) => (
                                                                        <span
                                                                            key={
                                                                                tag
                                                                            }
                                                                            className="rounded bg-muted/60 px-1.5 py-0.5 text-[11px] text-muted-foreground"
                                                                        >
                                                                            {
                                                                                tag
                                                                            }
                                                                        </span>
                                                                    ),
                                                                )}
                                                            </div>
                                                            <p className="mt-1 truncate text-sm font-semibold">
                                                                {memory.summary}
                                                            </p>
                                                            <p className="mt-0.5 text-sm text-muted-foreground">
                                                                {memory.content}
                                                            </p>
                                                            <p className="mt-0.5 text-xs text-muted-foreground/70">
                                                                {formatTime(
                                                                    memory.updated_at,
                                                                )}
                                                            </p>
                                                        </div>
                                                        <Button
                                                            type="button"
                                                            variant="ghost"
                                                            size="icon-sm"
                                                            aria-label={t(
                                                                "memory.delete",
                                                            )}
                                                            onClick={() => {
                                                                setMemoryToDelete(
                                                                    memory,
                                                                );
                                                                setDeleteError(
                                                                    null,
                                                                );
                                                            }}
                                                        >
                                                            <Trash2Icon className="size-4" />
                                                        </Button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                );
                            })}
                    </div>
                    <DialogFooter>
                        <DialogClose asChild>
                            <Button type="button" variant="outline">
                                {t("common.close")}
                            </Button>
                        </DialogClose>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog
                open={memoryToDelete !== null}
                onOpenChange={(next) => {
                    if (!next) {
                        setMemoryToDelete(null);
                        setDeleteError(null);
                    }
                }}
            >
                <DialogContent className="sm:max-w-sm">
                    <DialogHeader>
                        <DialogTitle>
                            {t("memory.deleteConfirmTitle")}
                        </DialogTitle>
                        <DialogDescription>
                            {t("memory.deleteConfirmDescription")}
                        </DialogDescription>
                    </DialogHeader>
                    {memoryToDelete && (
                        <div className="rounded-lg border bg-card p-3">
                            <p className="break-words whitespace-normal text-sm font-semibold">
                                {memoryToDelete.summary}
                            </p>
                            <p className="mt-0.5 break-words whitespace-normal text-sm text-muted-foreground">
                                {memoryToDelete.content}
                            </p>
                            <p className="mt-1 break-words whitespace-normal text-xs text-muted-foreground/70">
                                {memoryToDelete.key}:{" "}
                                {formatTime(memoryToDelete.updated_at)}
                            </p>
                        </div>
                    )}
                    {deleteError && (
                        <p className="text-sm text-destructive">
                            {deleteError}
                        </p>
                    )}
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
                                ? t("memory.deleting")
                                : t("memory.delete")}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
};
