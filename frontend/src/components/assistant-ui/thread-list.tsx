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
import {
  AuiIf,
  ThreadListItemMorePrimitive,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
} from "@assistant-ui/react";
import { MoreHorizontalIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { useState, useEffect, type FC, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

type ThreadListCallbacks = {
  onRename: (threadId: string, newTitle: string) => Promise<void> | void;
  onDelete: (threadId: string) => Promise<void> | void;
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
        condition={(s) => !s.threads.isLoading && s.threads.threadIds.length === 0}
      >
        <div className="rounded-lg border border-dashed px-3 py-5 text-sm text-muted-foreground">
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
        className="aui-thread-list-new h-9 justify-start gap-2 rounded-lg px-3 text-sm hover:bg-muted data-active:bg-muted"
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
  onDelete: (threadId: string) => Promise<void> | void;
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
    <ThreadListItemPrimitive.Root className="aui-thread-list-item group flex h-9 cursor-pointer items-center gap-1 rounded-lg transition-[background-color,color,box-shadow] hover:bg-muted focus-visible:bg-muted focus-visible:outline-none data-active:bg-sidebar-accent data-active:text-sidebar-accent-foreground data-active:shadow-sm">
      <ThreadListItemPrimitive.Trigger className="aui-thread-list-item-trigger flex h-full min-w-0 flex-1 cursor-pointer items-center px-3 text-start text-sm transition-colors">
        <span className="aui-thread-list-item-title min-w-0 flex-1 truncate">
          <ThreadListItemPrimitive.Title fallback={t("threadList.newChat")} />
        </span>
      </ThreadListItemPrimitive.Trigger>

      <ThreadListItemMorePrimitive.Root>
        <ThreadListItemMorePrimitive.Trigger asChild>
          <button
            type="button"
            aria-label={t("threadList.moreActions")}
            className="mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 transition-opacity hover:bg-background/60 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none group-hover:opacity-100 data-[state=open]:opacity-100"
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
  const [title, setTitle] = useState("");

  useEffect(() => {
    if (open) {
      setTitle(initialTitle ?? "");
    }
  }, [open, initialTitle]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = title.trim();
    if (trimmed) {
      void onRename(threadId, trimmed);
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("threadList.renameDialogTitle")}</DialogTitle>
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
  onDelete: (threadId: string) => Promise<void> | void;
};

const DeleteDialog: FC<DeleteDialogProps> = ({
  open,
  onOpenChange,
  threadId,
  onDelete,
}) => {
  const { t } = useTranslation();

  const handleConfirm = () => {
    void onDelete(threadId);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("threadList.deleteDialogTitle")}</DialogTitle>
          <DialogDescription>
            {t("threadList.deleteDialogDescription")}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              {t("common.cancel")}
            </Button>
          </DialogClose>
          <Button type="button" variant="destructive" onClick={handleConfirm}>
            {t("threadList.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
