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
import { Skeleton } from "@/components/ui/skeleton";
import { listMemoriesBySession } from "@/lib/nova-api";
import type { NovaMemoryRecord } from "@/types/nova";
import {
    AuiIf,
    ThreadListItemMorePrimitive,
    ThreadListItemPrimitive,
    ThreadListPrimitive,
} from "@assistant-ui/react";
import {
    MoreHorizontalIcon,
    PencilIcon,
    PlusIcon,
    Trash2Icon,
} from "lucide-react";
import { useEffect, useState, type FC, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

const TYPE_LABEL_KEY: Record<NovaMemoryRecord["memory_type"], string> = {
    fact: "memory.type.fact",
    preference: "memory.type.preference",
    decision: "memory.type.decision",
    context: "memory.type.context",
};

type ThreadListCallbacks = {
    onRename: (threadId: string, newTitle: string) => Promise<void> | void;
    onDelete: (
        threadId: string,
        deleteMemories?: boolean,
    ) => Promise<void> | void;
};

export const ThreadList: FC<ThreadListCallbacks> = ({ onRename, onDelete }) => {
    const { t } = useTranslation();
    return (
        <ThreadListPrimitive.Root className="aui-root aui-thread-list-root flex min-h-0 flex-col gap-1">
            <ThreadListNew />
            <AuiIf condition={(s) => s.threads.isLoading}>
                <ThreadListSkeleton />
            </AuiIf>
            <AuiIf
                condition={(s) =>
                    !s.threads.isLoading && s.threads.threadIds.length === 0
                }
            >
                <div className="rounded-lg border border-dashed border-sidebar-border px-3 py-5 text-sm text-sidebar-muted-foreground">
                    {t("threadList.savedSessionsAppearHere")}
                </div>
            </AuiIf>
            <AuiIf condition={(s) => !s.threads.isLoading}>
                <ThreadListPrimitive.Items>
                    {({ threadListItem }) => (
                        <ThreadListItem
                            threadId={threadListItem.id}
                            initialTitle={threadListItem.title}
                            onRename={onRename}
                            onDelete={onDelete}
                        />
                    )}
                </ThreadListPrimitive.Items>
            </AuiIf>
        </ThreadListPrimitive.Root>
    );
};

const ThreadListNew: FC = () => {
    const { t } = useTranslation();
    return (
        <ThreadListPrimitive.New asChild>
            <Button
                variant="outline"
                className="aui-thread-list-new h-9 justify-start gap-2 rounded-lg border-sidebar-border px-3 text-sm hover:bg-white hover:text-sidebar-accent-foreground data-active:bg-sidebar-accent"
            >
                <PlusIcon className="size-4" />
                {t("threadList.newThread")}
            </Button>
        </ThreadListPrimitive.New>
    );
};

const ThreadListSkeleton: FC = () => {
    const { t } = useTranslation();
    return (
        <div className="flex flex-col gap-1">
            {Array.from({ length: 5 }, (_, i) => (
                <div
                    key={i}
                    role="status"
                    aria-label={t("threadList.loadingThreads")}
                    className="aui-thread-list-skeleton-wrapper flex h-9 items-center px-3"
                >
                    <Skeleton className="aui-thread-list-skeleton h-4 w-full" />
                </div>
            ))}
        </div>
    );
};

type ThreadListItemProps = {
    threadId: string;
    initialTitle?: string;
    onRename: (threadId: string, newTitle: string) => Promise<void> | void;
    onDelete: (
        threadId: string,
        deleteMemories?: boolean,
    ) => Promise<void> | void;
};

const ThreadListItem: FC<ThreadListItemProps> = ({
    threadId,
    initialTitle,
    onRename,
    onDelete,
}) => {
    const { t } = useTranslation();
    const [renameOpen, setRenameOpen] = useState(false);
    const [deleteOpen, setDeleteOpen] = useState(false);

    return (
        <ThreadListItemPrimitive.Root className="aui-thread-list-item group flex h-9 cursor-pointer items-center gap-1 rounded-lg border border-transparent text-sidebar-foreground transition-[background-color_0.15s_ease] hover:bg-white focus-visible:border-[#E4E3DF] focus-visible:bg-white focus-visible:shadow-[0_2px_8px_rgba(20,20,18,0.06)] focus-visible:outline-none data-active:bg-white data-active:shadow-[0_1px_2px_rgba(20,20,18,0.05)] data-active:font-medium data-active:text-sidebar-active-foreground">
            <ThreadListItemPrimitive.Trigger className="aui-thread-list-item-trigger flex h-full min-w-0 flex-1 cursor-pointer items-center px-3 text-start text-sm transition-colors">
                <span className="aui-thread-list-item-title min-w-0 flex-1 truncate">
                    <ThreadListItemPrimitive.Title
                        fallback={t("threadList.newChat")}
                    />
                </span>
            </ThreadListItemPrimitive.Trigger>

            <ThreadListItemMorePrimitive.Root>
                <ThreadListItemMorePrimitive.Trigger asChild>
                    <button
                        type="button"
                        aria-label={t("threadList.moreActions")}
                        className="mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-sidebar-muted-foreground opacity-0 transition-opacity hover:bg-sidebar-foreground/10 hover:text-sidebar-foreground focus-visible:opacity-100 focus-visible:outline-none group-hover:opacity-100 data-[state=open]:opacity-100"
                    >
                        <MoreHorizontalIcon className="size-4" />
                    </button>
                </ThreadListItemMorePrimitive.Trigger>
                <ThreadListItemMorePrimitive.Content
                    align="end"
                    sideOffset={6}
                    className="z-50 min-w-36 overflow-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-md"
                >
                    <ThreadListItemMorePrimitive.Item
                        onSelect={() => setRenameOpen(true)}
                        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-muted"
                    >
                        <PencilIcon className="size-3.5 text-muted-foreground" />
                        {t("threadList.rename")}
                    </ThreadListItemMorePrimitive.Item>
                    <ThreadListItemMorePrimitive.Item
                        onSelect={() => setDeleteOpen(true)}
                        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-destructive outline-none data-[highlighted]:bg-destructive/10"
                    >
                        <Trash2Icon className="size-3.5" />
                        {t("threadList.delete")}
                    </ThreadListItemMorePrimitive.Item>
                </ThreadListItemMorePrimitive.Content>
            </ThreadListItemMorePrimitive.Root>

            <RenameDialog
                open={renameOpen}
                onOpenChange={setRenameOpen}
                threadId={threadId}
                initialTitle={initialTitle}
                onRename={onRename}
            />
            <DeleteDialog
                open={deleteOpen}
                onOpenChange={setDeleteOpen}
                threadId={threadId}
                onDelete={onDelete}
            />
        </ThreadListItemPrimitive.Root>
    );
};

type RenameDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    threadId: string;
    initialTitle?: string;
    onRename: (threadId: string, newTitle: string) => Promise<void> | void;
};

const RenameDialog: FC<RenameDialogProps> = ({
    open,
    onOpenChange,
    threadId,
    initialTitle,
    onRename,
}) => {
    const { t } = useTranslation();
    const [title, setTitle] = useState(initialTitle ?? "");

    const handleSubmit = (event: FormEvent) => {
        event.preventDefault();
        const trimmed = title.trim();
        if (trimmed) {
            void onRename(threadId, trimmed);
            onOpenChange(false);
        }
    };

    return (
        <Dialog
            key={open ? "rename-open" : "rename-closed"}
            open={open}
            onOpenChange={onOpenChange}
        >
            <DialogContent className="sm:max-w-sm">
                <DialogHeader>
                    <DialogTitle>
                        {t("threadList.renameDialogTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("threadList.renameDialogDescription")}
                    </DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit}>
                    <input
                        autoFocus
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder={t("threadList.renamePlaceholder")}
                        className="h-9 w-full rounded-md border bg-background px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/40"
                    />
                    <DialogFooter className="mt-4">
                        <DialogClose asChild>
                            <Button type="button" variant="outline">
                                {t("common.cancel")}
                            </Button>
                        </DialogClose>
                        <Button type="submit" disabled={!title.trim()}>
                            {t("threadList.rename")}
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
};

type DeleteDialogProps = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    threadId: string;
    onDelete: (
        threadId: string,
        deleteMemories?: boolean,
    ) => Promise<void> | void;
};

const DeleteDialog: FC<DeleteDialogProps> = ({
    open,
    onOpenChange,
    threadId,
    onDelete,
}) => {
    const { t } = useTranslation();
    const [deleteMemories, setDeleteMemories] = useState(false);
    const [sessionMemories, setSessionMemories] = useState<NovaMemoryRecord[]>(
        [],
    );
    const [memoriesLoading, setMemoriesLoading] = useState(true);
    const [memoriesError, setMemoriesError] = useState<string | null>(null);

    useEffect(() => {
        if (!open) {
            return;
        }
        let cancelled = false;
        listMemoriesBySession(threadId)
            .then((items) => {
                if (!cancelled) {
                    setSessionMemories(items);
                }
            })
            .catch((error) => {
                if (!cancelled) {
                    setMemoriesError(
                        error instanceof Error ? error.message : String(error),
                    );
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setMemoriesLoading(false);
                }
            });
        return () => {
            cancelled = true;
        };
    }, [open, threadId]);

    const handleConfirm = () => {
        void onDelete(threadId, deleteMemories);
        onOpenChange(false);
    };

    return (
        <Dialog
            key={open ? "delete-open" : "delete-closed"}
            open={open}
            onOpenChange={onOpenChange}
        >
            <DialogContent className="sm:max-w-sm">
                <DialogHeader>
                    <DialogTitle>
                        {t("threadList.deleteDialogTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("threadList.deleteDialogDescription")}
                    </DialogDescription>
                </DialogHeader>
                <div className="max-h-40 overflow-y-auto rounded-md border p-2">
                    {memoriesLoading && (
                        <p className="px-1 py-2 text-xs text-muted-foreground">
                            {t("threadList.loadingMemories")}
                        </p>
                    )}
                    {!memoriesLoading && memoriesError && (
                        <p className="px-1 py-2 text-xs text-destructive">
                            {memoriesError}
                        </p>
                    )}
                    {!memoriesLoading &&
                        !memoriesError &&
                        sessionMemories.length === 0 && (
                            <p className="px-1 py-2 text-xs text-muted-foreground">
                                {t("threadList.noMemories")}
                            </p>
                        )}
                    {!memoriesLoading &&
                        !memoriesError &&
                        sessionMemories.length > 0 && (
                            <ul className="flex flex-col gap-1">
                                {sessionMemories.map((memory) => (
                                    <li
                                        key={memory.id}
                                        className="flex items-center gap-2 rounded bg-muted/60 px-2 py-1.5"
                                    >
                                        <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] font-medium text-muted-foreground">
                                            {t(
                                                TYPE_LABEL_KEY[
                                                    memory.memory_type
                                                ],
                                            )}
                                        </span>
                                        <span className="min-w-0 flex-1 truncate text-xs">
                                            {memory.summary || memory.key}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                </div>
                <label className="flex cursor-pointer items-start gap-2.5 rounded-md border p-3">
                    <input
                        type="checkbox"
                        checked={deleteMemories}
                        onChange={(event) =>
                            setDeleteMemories(event.target.checked)
                        }
                        className="mt-0.5 size-4 shrink-0 accent-destructive"
                    />
                    <span className="text-sm">
                        <span className="block font-medium text-foreground">
                            {t("threadList.deleteMemoriesLabel")}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                            {t("threadList.deleteMemoriesDescription")}
                        </span>
                    </span>
                </label>
                <DialogFooter>
                    <DialogClose asChild>
                        <Button type="button" variant="outline">
                            {t("common.cancel")}
                        </Button>
                    </DialogClose>
                    <Button
                        type="button"
                        variant="destructive"
                        onClick={handleConfirm}
                    >
                        {t("threadList.delete")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
