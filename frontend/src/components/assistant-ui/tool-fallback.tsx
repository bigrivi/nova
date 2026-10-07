"use client";

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { errorTextFromResult } from "@/lib/tool-result";
import { readToolOutcome } from "@/lib/tool-outcome";
import {
    readBackgroundTaskEnvelope,
    readBackgroundTaskReference,
} from "@/lib/background-task";
import { useBackgroundTaskStore } from "@/stores/background-task-store";
import type { NovaBackgroundTask, NovaBackgroundTaskStatus } from "@/types/nova";

import {
    useScrollLock,
    type ToolCallMessagePartComponent,
    type ToolCallMessagePartStatus,
} from "@assistant-ui/react";
import {
    AlertCircleIcon,
    CheckIcon,
    ChevronDownIcon,
    Clock3Icon,
    LoaderIcon,
    XCircleIcon,
} from "lucide-react";
import { memo, useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const TERMINAL_TASK_STATUSES: ReadonlySet<NovaBackgroundTaskStatus> = new Set([
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "interrupted",
]);

function isTerminalTaskStatus(status: NovaBackgroundTaskStatus): boolean {
    return TERMINAL_TASK_STATUSES.has(status);
}

const ANIMATION_DURATION = 200;

export type ToolFallbackRootProps = Omit<
    React.ComponentProps<typeof Collapsible>,
    "open" | "onOpenChange"
> & {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    defaultOpen?: boolean;
};

function ToolFallbackRoot({
    className,
    open: controlledOpen,
    onOpenChange: controlledOnOpenChange,
    defaultOpen = false,
    children,
    ...props
}: ToolFallbackRootProps) {
    const collapsibleRef = useRef<HTMLDivElement>(null);
    const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
    const lockScroll = useScrollLock(collapsibleRef, ANIMATION_DURATION);

    const isControlled = controlledOpen !== undefined;
    const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

    const handleOpenChange = useCallback(
        (open: boolean) => {
            if (!open) {
                lockScroll();
            }
            if (!isControlled) {
                setUncontrolledOpen(open);
            }
            controlledOnOpenChange?.(open);
        },
        [lockScroll, isControlled, controlledOnOpenChange],
    );

    return (
        <Collapsible
            ref={collapsibleRef}
            data-slot="tool-fallback-root"
            open={isOpen}
            onOpenChange={handleOpenChange}
            className={cn(
                "aui-tool-fallback-root group/tool-fallback-root w-full max-w-full min-w-0",
                className,
            )}
            style={
                {
                    "--animation-duration": `${ANIMATION_DURATION}ms`,
                } as React.CSSProperties
            }
            {...props}
        >
            {children}
        </Collapsible>
    );
}

function getParamSummary(argsText?: string): string | null {
    if (!argsText) return null;
    const trimmed = argsText.trim();
    if (!trimmed) return null;
    try {
        const parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            const candidates = [
                "filePath",
                "path",
                "file",
                "pattern",
                "query",
                "command",
                "url",
                "glob",
                "prompt",
            ];
            for (const k of candidates) {
            const v = (parsed as Record<string, unknown>)[k];
                if (typeof v === "string" && v.trim()) {
                    return v.trim();
                }
            }
            for (const v of Object.values(parsed)) {
                if (typeof v === "string" && v.trim()) {
                    return v.trim();
                }
            }
            return trimmed;
        }
    } catch {
        return trimmed;
    }
    return trimmed;
}

function ToolFallbackTrigger({
    toolName,
    argsText,
    status,
    isError,
    backgroundTaskLabel,
    backgroundTaskStatus,
    backgroundState,
    className,
    ...props
}: React.ComponentProps<typeof CollapsibleTrigger> & {
    toolName: string;
    argsText?: string;
    status?: ToolCallMessagePartStatus;
    isError?: boolean;
    backgroundTaskLabel?: string;
    backgroundTaskStatus?: string | null;
    backgroundState?: NovaBackgroundTaskStatus | null;
}) {
    const statusType = status?.type ?? "complete";
    const { isRunning, isCancelled, errored } = readToolOutcome(
        status,
        isError,
        backgroundState ?? null,
    );
    const paramSummary = getParamSummary(argsText);

    return (
        <CollapsibleTrigger
            data-slot="tool-fallback-trigger"
            className={cn(
                "aui-tool-fallback-trigger group/trigger flex w-full cursor-pointer items-center gap-[9px] bg-card px-3 py-[10px] text-left hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/20 focus-visible:ring-inset motion-reduce:transition-none",
                className,
            )}
            {...props}
        >
            <span
                aria-hidden="true"
                data-slot="tool-fallback-status-dot"
                className={cn(
                    "flex size-[15px] shrink-0 items-center justify-center rounded-full",
                    isRunning && "bg-[#F7EEDD] text-[#A5750F]",
                    !isRunning && !isCancelled && !errored && "bg-[#E5F3EB] text-[#157A4A]",
                    isCancelled && "bg-muted text-weak",
                    errored && "bg-danger-soft text-danger",
                    statusType === "requires-action" && !errored && "bg-[#F7EEDD] text-[#A5750F]",
                )}
            >
                {isRunning ? (
                    <LoaderIcon className="size-[10px] animate-spin motion-reduce:animate-none" aria-hidden="true" />
                ) : isCancelled ? (
                    <XCircleIcon className="size-[10px]" aria-hidden="true" />
                ) : errored ? (
                    <XCircleIcon className="size-[10px]" aria-hidden="true" />
                ) : statusType === "requires-action" ? (
                    <AlertCircleIcon className="size-[10px]" aria-hidden="true" />
                ) : (
                    <CheckIcon className="size-[10px]" strokeWidth={3} aria-hidden="true" />
                )}
            </span>
            <span
                data-slot="tool-fallback-trigger-label"
                className={cn(
                    "flex min-w-0 grow items-baseline gap-2 text-start leading-none",
                    isCancelled && "line-through opacity-60",
                )}
            >
                <span className="shrink-0 font-mono text-[12.5px] font-medium text-foreground">
                    {toolName}
                </span>
                {paramSummary ? (
                    <span
                        title={paramSummary}
                        className="truncate font-mono text-[12px] font-normal text-weak"
                    >
                        {paramSummary}
                    </span>
                ) : null}
            </span>
            {backgroundTaskLabel ? (
                <span
                    data-slot="tool-fallback-background-task"
                    className="flex shrink-0 items-center gap-1 rounded-full bg-brand-soft px-2 py-1 font-sans text-[10px] font-medium text-brand"
                    title={backgroundTaskStatus ?? backgroundTaskLabel}
                >
                    <Clock3Icon className="size-3" aria-hidden="true" />
                    <span>{backgroundTaskLabel}</span>
                    {backgroundTaskStatus ? (
                        <span className="hidden max-[520px]:hidden sm:inline">
                            · {backgroundTaskStatus}
                        </span>
                    ) : null}
                </span>
            ) : null}
            <ChevronDownIcon
                data-slot="tool-fallback-trigger-chevron"
                className={cn(
                    "aui-tool-fallback-trigger-chevron size-[14px] shrink-0 text-weak",
                    "transition-transform duration-(--animation-duration) ease-out motion-reduce:transition-none",
                    "group-data-[state=closed]/trigger:-rotate-90",
                    "group-data-[state=open]/trigger:rotate-0",
                )}
                aria-hidden="true"
            />
        </CollapsibleTrigger>
    );
}

function ToolFallbackContent({
    className,
    children,
    ...props
}: React.ComponentProps<typeof CollapsibleContent>) {
    return (
        <CollapsibleContent
            data-slot="tool-fallback-content"
            className={cn(
                "aui-tool-fallback-content relative overflow-hidden text-sm outline-none",
                "group/collapsible-content ease-out motion-reduce:transition-none",
                "data-[state=closed]:animate-collapsible-up motion-reduce:data-[state=closed]:animate-none",
                "data-[state=open]:animate-collapsible-down motion-reduce:data-[state=open]:animate-none",
                "data-[state=closed]:fill-mode-forwards",
                "data-[state=closed]:pointer-events-none",
                "data-[state=open]:duration-(--animation-duration)",
                "data-[state=closed]:duration-(--animation-duration)",
                className,
            )}
            {...props}
        >
            <div className="flex min-w-0 max-w-full flex-col gap-2 border-t border-border bg-muted/40 px-[14px] py-3 pl-6 font-mono text-[12px] leading-[1.7] text-weak-strong min-[520px]:pl-10">
                {children}
            </div>
        </CollapsibleContent>
    );
}

function ToolFallbackArgs({
    argsText,
    className,
    ...props
}: React.ComponentProps<"div"> & {
    argsText?: string;
}) {
    if (!argsText) return null;

    return (
        <div
            data-slot="tool-fallback-args"
            className={cn("aui-tool-fallback-args", className)}
            {...props}
        >
            <pre className="aui-tool-fallback-args-value whitespace-pre-wrap break-words">
                {argsText}
            </pre>
        </div>
    );
}

function ToolFallbackResult({
    result,
    liveTask,
    className,
    ...props
}: React.ComponentProps<"div"> & {
    result?: unknown;
    liveTask?: NovaBackgroundTask | null;
}) {
    const { t } = useTranslation();

    // A settled background task replaces its handle with the real output, so
    // the card reads like a finished tool call rather than "still running".
    if (liveTask && isTerminalTaskStatus(liveTask.status)) {
        const body =
            liveTask.output_tail?.trim() ||
            liveTask.result?.trim() ||
            liveTask.error?.trim() ||
            "";
        return (
            <div
                data-slot="tool-fallback-result"
                className={cn(
                    "aui-tool-fallback-result border-t border-dashed border-border pt-2",
                    className,
                )}
                {...props}
            >
                <p className="font-semibold text-foreground">
                    {t(`tasks.status.${liveTask.status}`)}
                    {typeof liveTask.exit_code === "number"
                        ? ` · exit ${liveTask.exit_code}`
                        : ""}
                </p>
                {body ? (
                    <pre className="mt-1 whitespace-pre-wrap break-words">
                        {body}
                    </pre>
                ) : null}
                {liveTask.output_truncated ? (
                    <p className="mt-1 text-[11px] text-muted-foreground">
                        {t("tasks.outputTruncated")}
                    </p>
                ) : null}
            </div>
        );
    }

    if (result === undefined) return null;
    const backgroundTask = readBackgroundTaskEnvelope(result);
    if (backgroundTask) {
        return (
            <div
                data-slot="tool-fallback-result"
                className={cn(
                    "aui-tool-fallback-result border-t border-dashed border-border pt-2",
                    className,
                )}
                {...props}
            >
                <p className="font-semibold text-foreground">
                    {t("tools.backgroundTask")}
                </p>
                {backgroundTask.message ? (
                    <p className="mt-1 whitespace-pre-wrap break-words font-sans text-weak-strong">
                        {backgroundTask.message}
                    </p>
                ) : null}
                {backgroundTask.taskId ? (
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                        {t("tasks.taskId")}: {backgroundTask.taskId}
                    </p>
                ) : null}
            </div>
        );
    }

    return (
        <div
            data-slot="tool-fallback-result"
            className={cn("aui-tool-fallback-result border-t border-dashed border-border pt-2", className)}
            {...props}
        >
            <p className="aui-tool-fallback-result-header font-semibold text-foreground">
                {t("tools.result")}
            </p>
            <pre className="aui-tool-fallback-result-content whitespace-pre-wrap break-words">
                {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
            </pre>
        </div>
    );
}

function ToolFallbackError({
    status,
    message,
    className,
    ...props
}: React.ComponentProps<"div"> & {
    status?: ToolCallMessagePartStatus;
    message?: string | null;
}) {
    const { t } = useTranslation();

    const statusErrorText =
        status?.type === "incomplete" && status.error != null
            ? typeof status.error === "string"
                ? status.error
                : JSON.stringify(status.error)
            : null;
    const errorText = message?.trim() ? message.trim() : statusErrorText;

    if (!errorText) return null;

    const isCancelled =
        status?.type === "incomplete" && status.reason === "cancelled";
    const headerText = isCancelled ? t("tools.cancelledReason") : t("tools.error");

    return (
        <div data-slot="tool-fallback-error" className={cn("aui-tool-fallback-error", className)} {...props}>
            <p className="aui-tool-fallback-error-header font-semibold text-danger">
                {headerText}
            </p>
            <p className="aui-tool-fallback-error-reason whitespace-pre-wrap break-words text-weak-strong">
                {errorText}
            </p>
        </div>
    );
}

const ToolFallbackImpl: ToolCallMessagePartComponent = ({
    toolName,
    argsText,
    result,
    status,
    isError,
}) => {
    const { t } = useTranslation();
    // Part status only: the detached task is deliberately excluded here so the
    // result block stays rendered for a task that later fails.
    const { isCancelled, errored } = readToolOutcome(status, isError, null);
    const errorMessage = errored ? errorTextFromResult(result) : null;
    const backgroundTask = readBackgroundTaskReference(argsText, result);
    const trackedTask = useBackgroundTaskStore((state) =>
        backgroundTask?.taskId
            ? state.tasksById[backgroundTask.taskId]
            : undefined,
    );
    const backgroundStatus =
        trackedTask?.status ?? backgroundTask?.status ?? null;
    const backgroundStatusLabel = backgroundStatus
        ? t(`tasks.status.${backgroundStatus}`)
        : null;

    return (
        <ToolFallbackRoot className={cn(isCancelled && "opacity-80")}>
            <ToolFallbackTrigger
                toolName={toolName}
                argsText={argsText}
                status={status}
                isError={isError}
                backgroundTaskLabel={
                    backgroundTask ? t("tools.backgroundTask") : undefined
                }
                backgroundTaskStatus={backgroundStatusLabel}
                backgroundState={trackedTask?.status ?? null}
            />
            <ToolFallbackContent>
                <ToolFallbackError status={status} message={errorMessage} />
                <ToolFallbackArgs argsText={argsText} className={cn(isCancelled && "opacity-60")} />
                {!isCancelled && !errored && (
                    <ToolFallbackResult result={result} liveTask={trackedTask} />
                )}
            </ToolFallbackContent>
        </ToolFallbackRoot>
    );
};

const ToolFallback = memo(
    ToolFallbackImpl,
) as unknown as ToolCallMessagePartComponent & {
    Root: typeof ToolFallbackRoot;
    Trigger: typeof ToolFallbackTrigger;
    Content: typeof ToolFallbackContent;
    Args: typeof ToolFallbackArgs;
    Result: typeof ToolFallbackResult;
    Error: typeof ToolFallbackError;
};

ToolFallback.displayName = "ToolFallback";
ToolFallback.Root = ToolFallbackRoot;
ToolFallback.Trigger = ToolFallbackTrigger;
ToolFallback.Content = ToolFallbackContent;
ToolFallback.Args = ToolFallbackArgs;
ToolFallback.Result = ToolFallbackResult;
ToolFallback.Error = ToolFallbackError;

export {
    ToolFallback,
    ToolFallbackArgs,
    ToolFallbackContent,
    ToolFallbackError,
    ToolFallbackResult,
    ToolFallbackRoot,
    ToolFallbackTrigger,
};
