import { AskUserTool } from "@/components/assistant-ui/ask-user-tool";
import { UserMessageAttachments } from "@/components/assistant-ui/attachment";
import { FileMutationTool } from "@/components/assistant-ui/file-mutation-tool";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { Reasoning, ReasoningGroup } from "@/components/assistant-ui/reasoning";
import { ThreadStickyComposer } from "@/components/assistant-ui/thread-sticky-composer";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { NovaModelRecord, NovaProviderRecord } from "@/types/nova";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  SuggestionPrimitive,
  ThreadPrimitive,
  useAssistantToolUI,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  BotIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  MoreHorizontalIcon,
  RefreshCwIcon,
} from "lucide-react";
import type { KeyboardEvent, RefObject } from "react";
import { type FC, useEffect, useState } from "react";

const ASSISTANT_NAME = "Nova";
const SCROLL_TO_BOTTOM_THRESHOLD = 32;

type ThreadProps = {
  composer: {
    ref: RefObject<HTMLTextAreaElement | null>;
    text: string;
    isRunning: boolean;
    onChange: (value: string) => void;
    onSubmit: () => void;
    onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  };
  status: {
    text: string;
    error: string | null;
  };
  modelSelection: {
    models: NovaModelRecord[];
    providers: NovaProviderRecord[];
    selectedModelId: string | null;
    onSelect: (modelId: string) => void;
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onStatusChange: (message: string | null) => void;
  };
};

export const Thread: FC<ThreadProps> = ({
  composer,
  status,
  modelSelection,
}) => {
  const [composerHeight, setComposerHeight] = useState(0);
  const [viewportScrollbarWidth, setViewportScrollbarWidth] = useState(0);

  useEffect(() => {
    const viewport = document.querySelector<HTMLElement>(
      '[data-slot="aui_thread-viewport"]',
    );
    if (!viewport) {
      setViewportScrollbarWidth(0);
      return;
    }

    const updateScrollbarWidth = () => {
      setViewportScrollbarWidth(viewport.offsetWidth - viewport.clientWidth);
    };

    updateScrollbarWidth();

    const observer = new ResizeObserver(() => {
      updateScrollbarWidth();
    });
    observer.observe(viewport);
    window.addEventListener("resize", updateScrollbarWidth);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateScrollbarWidth);
    };
  }, []);

  return (
    <>
      <CustomToolUIRegistry />
      <ThreadPrimitive.Root
        className="aui-root aui-thread-root @container relative flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background"
        style={{
          ["--thread-max-width" as string]: "44rem",
          ["--composer-radius" as string]: "24px",
          ["--composer-padding" as string]: "10px",
        }}
      >
        <ThreadPrimitive.Viewport
          autoScroll
          data-slot="aui_thread-viewport"
          className="relative flex min-h-0 flex-1 flex-col overflow-y-auto scroll-smooth"
        >
          <div className="mx-auto flex min-h-full w-full max-w-(--thread-max-width) flex-col px-4 pt-4">
            <AuiIf condition={(s) => s.thread.isEmpty}>
              <ThreadWelcome />
            </AuiIf>

            <div
              data-slot="aui_message-group"
              className="mb-5 flex flex-col gap-y-2 empty:hidden"
            >
              <ThreadPrimitive.Messages>
                {() => <ThreadMessage />}
              </ThreadPrimitive.Messages>
            </div>

            <div
              aria-hidden="true"
              className="shrink-0"
              style={{
                height: composerHeight ? `${composerHeight + 20}px` : "0px",
              }}
            />

            <ThreadScrollToBottom />
          </div>
        </ThreadPrimitive.Viewport>

        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 z-20"
          style={{
            paddingRight: viewportScrollbarWidth
              ? `${viewportScrollbarWidth}px`
              : undefined,
          }}
        >
          <ThreadStickyComposer
            composer={composer}
            status={status}
            modelSelection={modelSelection}
            onHeightChange={setComposerHeight}
          />
        </div>
      </ThreadPrimitive.Root>
    </>
  );
};

const CustomToolUIRegistry: FC = () => {
  useAssistantToolUI({
    toolName: "ask_user",
    render: AskUserTool,
  });

  useAssistantToolUI({
    toolName: "edit",
    render: FileMutationTool,
  });

  useAssistantToolUI({
    toolName: "write",
    render: FileMutationTool,
  });

  return null;
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);

  if (role === "user") return <UserMessage />;
  return <AssistantMessage />;
};

const ThreadScrollToBottom: FC = () => {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const viewport = document.querySelector<HTMLElement>(
      '[data-slot="aui_thread-viewport"]',
    );
    if (!viewport) {
      setIsVisible(false);
      return;
    }

    const updateVisibility = () => {
      const distanceToBottom =
        viewport.scrollHeight - (viewport.scrollTop + viewport.clientHeight);
      setIsVisible(distanceToBottom > SCROLL_TO_BOTTOM_THRESHOLD);
    };

    updateVisibility();
    viewport.addEventListener("scroll", updateVisibility, { passive: true });
    window.addEventListener("resize", updateVisibility);

    return () => {
      viewport.removeEventListener("scroll", updateVisibility);
      window.removeEventListener("resize", updateVisibility);
    };
  }, []);

  if (!isVisible) {
    return null;
  }

  return (
    <div className="pointer-events-none sticky bottom-28 z-10 flex overflow-visible pb-4 md:bottom-32 md:pb-6">
      <TooltipIconButton
        tooltip="Scroll to bottom"
        variant="outline"
        className="pointer-events-auto absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-background/95 p-3 shadow-sm backdrop-blur"
        onClick={() => {
          const viewport = document.querySelector<HTMLElement>(
            '[data-slot="aui_thread-viewport"]',
          );
          viewport?.scrollTo({
            top: viewport.scrollHeight,
            behavior: "smooth",
          });
        }}
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </div>
  );
};

const ThreadWelcome: FC = () => {
  return (
    <div className="aui-thread-welcome-root my-auto flex grow flex-col">
      <div className="aui-thread-welcome-center flex w-full grow flex-col items-center justify-center">
        <div className="aui-thread-welcome-message flex size-full flex-col justify-center px-4">
          <h1 className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both font-semibold text-2xl duration-200">
            Hello there!
          </h1>
          <p className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both text-muted-foreground text-xl delay-75 duration-200">
            How can I help you today?
          </p>
        </div>
      </div>
      <ThreadSuggestions />
    </div>
  );
};

const ThreadSuggestions: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestions grid w-full @md:grid-cols-2 gap-2 pb-4">
      <ThreadPrimitive.Suggestions>
        {() => <ThreadSuggestionItem />}
      </ThreadPrimitive.Suggestions>
    </div>
  );
};

const ThreadSuggestionItem: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestion-display fade-in slide-in-from-bottom-2 @md:nth-[n+3]:block nth-[n+3]:hidden animate-in fill-mode-both duration-200">
      <SuggestionPrimitive.Trigger send asChild>
        <Button
          variant="ghost"
          className="aui-thread-welcome-suggestion h-auto w-full @md:flex-col flex-wrap items-start justify-start gap-1 rounded-3xl border bg-background px-4 py-3 text-start text-sm transition-colors hover:bg-muted"
        >
          <SuggestionPrimitive.Title className="aui-thread-welcome-suggestion-text-1 font-medium" />
          <SuggestionPrimitive.Description className="aui-thread-welcome-suggestion-text-2 text-muted-foreground empty:hidden" />
        </Button>
      </SuggestionPrimitive.Trigger>
    </div>
  );
};

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root mt-2 rounded-md border border-destructive bg-destructive/10 p-3 text-destructive text-sm dark:bg-destructive/5 dark:text-red-200">
        <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

const AssistantMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_assistant-message-root"
      data-role="assistant"
      className="fade-in slide-in-from-bottom-1 flex animate-in flex-col gap-y-2 duration-150"
    >
      <div className="flex min-w-0 items-center gap-2 leading-none">
        <Avatar
          size="sm"
          className="size-6 border border-emerald-200/80 bg-emerald-50 text-emerald-900 shadow-sm after:hidden"
        >
          <AvatarFallback className="bg-transparent text-emerald-900">
            <BotIcon className="size-3" />
          </AvatarFallback>
        </Avatar>
        <span className="text-[12px] font-medium tracking-[0.01em] text-muted-foreground">
          {ASSISTANT_NAME}
        </span>
      </div>

      <div
        data-slot="aui_assistant-message-content"
        className="wrap-break-word min-w-0 text-foreground leading-relaxed"
      >
        <MessagePrimitive.Parts
          components={{
            Text: MarkdownText,
            Reasoning,
            ReasoningGroup,
            tools: { Fallback: ToolFallback },
          }}
        />
        <MessageError />
      </div>

      <div
        data-slot="aui_assistant-message-footer"
        className="relative min-h-7 pt-1.5"
      >
        <BranchPicker />
        <AssistantActionBar />
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-assistant-action-bar-root absolute left-0 top-1.5 flex gap-1 text-muted-foreground"
    >
      <ActionBarPrimitive.Copy asChild>
        <TooltipIconButton tooltip="Copy">
          <AuiIf condition={(s) => s.message.isCopied}>
            <CheckIcon />
          </AuiIf>
          <AuiIf condition={(s) => !s.message.isCopied}>
            <CopyIcon />
          </AuiIf>
        </TooltipIconButton>
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.Reload asChild>
        <TooltipIconButton tooltip="Refresh">
          <RefreshCwIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Reload>
      <ActionBarMorePrimitive.Root>
        <ActionBarMorePrimitive.Trigger asChild>
          <TooltipIconButton
            tooltip="More"
            className="data-[state=open]:bg-accent"
          >
            <MoreHorizontalIcon />
          </TooltipIconButton>
        </ActionBarMorePrimitive.Trigger>
        <ActionBarMorePrimitive.Content
          side="bottom"
          align="start"
          className="aui-action-bar-more-content z-50 min-w-32 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <ActionBarPrimitive.ExportMarkdown asChild>
            <ActionBarMorePrimitive.Item className="aui-action-bar-more-item flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground">
              <DownloadIcon className="size-4" />
              Export as Markdown
            </ActionBarMorePrimitive.Item>
          </ActionBarPrimitive.ExportMarkdown>
        </ActionBarMorePrimitive.Content>
      </ActionBarMorePrimitive.Root>
    </ActionBarPrimitive.Root>
  );
};

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      data-slot="aui_user-message-root"
      className="fade-in slide-in-from-bottom-1 grid animate-in auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 duration-150 [&:where(>*)]:col-start-2"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
        <div className="aui-user-message-content wrap-break-word rounded-2xl bg-muted px-4 py-2.5 text-foreground empty:hidden">
          <MessagePrimitive.Parts />
        </div>
      </div>
    </MessagePrimitive.Root>
  );
};

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({
  className,
  ...rest
}) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "aui-branch-picker-root -ms-2 me-2 inline-flex items-center text-muted-foreground text-xs",
        className,
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <TooltipIconButton tooltip="Previous">
          <ChevronLeftIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Previous>
      <span className="aui-branch-picker-state font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <TooltipIconButton tooltip="Next">
          <ChevronRightIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};
