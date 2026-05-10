import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AuiIf,
  ThreadListItemPrimitive,
  ThreadListPrimitive,
} from "@assistant-ui/react";
import { PlusIcon } from "lucide-react";
import type { FC } from "react";
import { useTranslation } from "react-i18next";

export const ThreadList: FC = () => {
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
          {() => <ThreadListItem />}
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

const ThreadListItem: FC = () => {
  const { t } = useTranslation();
  return (
    <ThreadListItemPrimitive.Root className="aui-thread-list-item group flex h-9 items-center gap-2 rounded-lg transition-[background-color,color,box-shadow] hover:bg-muted focus-visible:bg-muted focus-visible:outline-none data-active:bg-sidebar-accent data-active:text-sidebar-accent-foreground data-active:shadow-sm">
      <ThreadListItemPrimitive.Trigger className="aui-thread-list-item-trigger flex h-full min-w-0 flex-1 items-center px-3 text-start text-sm transition-colors">
        <span className="aui-thread-list-item-title min-w-0 flex-1 truncate">
          <ThreadListItemPrimitive.Title fallback={t("threadList.newChat")} />
        </span>
      </ThreadListItemPrimitive.Trigger>
    </ThreadListItemPrimitive.Root>
  );
};
