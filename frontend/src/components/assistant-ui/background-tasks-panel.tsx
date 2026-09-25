"use client";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import { cancelBackgroundTask } from "@/lib/nova-api";
import { cn } from "@/lib/utils";
import { useBackgroundTaskStore } from "@/stores/background-task-store";
import type { NovaBackgroundTask, NovaBackgroundTaskStatus } from "@/types/nova";
import {
    CheckCircle2Icon,
    ChevronDownIcon,
    CircleIcon,
    Loader2Icon,
    SquareIcon,
    XCircleIcon,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

const EMPTY_TASKS: NovaBackgroundTask[] = [];

function formatDuration(task: NovaBackgroundTask): string {
    const end = task.finished_at_ms ?? Date.now();
    const start = task.started_at_ms ?? task.created_at_ms;
    const totalSeconds = Math.max(0, Math.floor((end - start) / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function statusIcon(status: NovaBackgroundTaskStatus) {
    if (status === "running" || status === "queued") {
        return <Loader2Icon className="size-3.5 animate-spin motion-reduce:animate-none" />;
    }
    if (status === "succeeded") {
        return <CheckCircle2Icon className="size-3.5" />;
    }
    if (status === "failed" || status === "timed_out") {
        return <XCircleIcon className="size-3.5" />;
    }
    if (status === "cancelled") {
        return <SquareIcon className="size-3.5" />;
    }
    return <CircleIcon className="size-3.5" />;
}

export function BackgroundTasksPanel() {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [taskToCancel, setTaskToCancel] = useState<NovaBackgroundTask | null>(
        null,
    );
    const sessionId = useBackgroundTaskStore((state) => state.activeSessionId);
    const tasksBySession = useBackgroundTaskStore(
        (state) => state.tasksBySession,
    );
    const tasks = sessionId
        ? (tasksBySession[sessionId] ?? EMPTY_TASKS)
        : EMPTY_TASKS;
    const error = useBackgroundTaskStore((state) => state.error);
    const updateTask = useBackgroundTaskStore((state) => state.updateTask);
    const setError = useBackgroundTaskStore((state) => state.setError);
    const activeCount = tasks.filter(
        (task) => task.status === "running" || task.status === "queued",
    ).length;

    if (tasks.length === 0 && !error) return null;

    const confirmCancel = () => {
        if (!sessionId || !taskToCancel) return;
        void cancelBackgroundTask(taskToCancel.task_id, sessionId)
            .then(() => {
                updateTask({ ...taskToCancel, status: "cancelled" });
            })
            .catch((cancelError: unknown) => {
                setError(
                    cancelError instanceof Error
                        ? cancelError.message
                        : t("tasks.cancelError"),
                );
            });
        setTaskToCancel(null);
    };

    return (
        <div className="pointer-events-auto pb-2">
            <div className="relative w-full rounded-t-lg border border-b-0 border-[#E4E1D9] bg-[#FAFAF9] shadow-[0_1px_2px_rgba(20,20,18,0.04),0_8px_20px_rgba(20,20,18,0.05)]">
                <button
                    type="button"
                    onClick={() => setOpen((value) => !value)}
                    aria-expanded={open}
                    className="flex w-full items-center gap-2.5 rounded-t-lg px-4 py-2.5 text-sm hover:bg-muted/50"
                >
                    <Loader2Icon
                        className={cn(
                            "size-4 shrink-0 text-[#A5750F]",
                            activeCount > 0 &&
                                "animate-spin motion-reduce:animate-none",
                        )}
                        aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate text-start leading-none">
                        {t("tasks.backgroundTitle")}
                    </span>
                    <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums text-muted-foreground">
                        {activeCount}
                    </span>
                    <ChevronDownIcon
                        className={cn(
                            "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                            open && "rotate-180",
                        )}
                        aria-hidden="true"
                    />
                </button>

                {open ? (
                    <div className="max-h-64 overflow-y-auto border-t border-[#ECECEA] px-3 py-2">
                        {error ? (
                            <p className="px-1 py-2 text-xs text-[#B23B2E]">
                                {error}
                            </p>
                        ) : null}
                        <ul className="space-y-2">
                            {tasks.map((task) => (
                                <li
                                    key={task.task_id}
                                    className="rounded-lg border border-[#E4E3DF] bg-white px-3 py-2"
                                >
                                    <div className="flex min-w-0 items-center gap-2">
                                        <span
                                            className={cn(
                                                "shrink-0",
                                                task.status === "running" ||
                                                    task.status === "queued"
                                                    ? "text-[#A5750F]"
                                                    : task.status === "succeeded"
                                                      ? "text-[#157A4A]"
                                                      : task.status === "failed" ||
                                                          task.status === "timed_out"
                                                        ? "text-[#B23B2E]"
                                                        : "text-[#9C978A]",
                                            )}
                                            aria-hidden="true"
                                        >
                                            {statusIcon(task.status)}
                                        </span>
                                        <span className="min-w-0 flex-1 truncate text-xs font-medium text-[#1C1B18]">
                                            {task.label}
                                        </span>
                                        <span className="hidden shrink-0 text-[10px] text-muted-foreground sm:inline">
                                            {t(`tasks.status.${task.status}`)}
                                        </span>
                                        <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                                            {formatDuration(task)}
                                        </span>
                                        {task.status === "running" ||
                                        task.status === "queued" ? (
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="icon-sm"
                                                aria-label={t("tasks.stop")}
                                                title={t("tasks.stop")}
                                                onClick={() => setTaskToCancel(task)}
                                            >
                                                <SquareIcon className="size-3.5 fill-current" />
                                            </Button>
                                        ) : null}
                                    </div>
                                    {task.progress_message ? (
                                        <p className="mt-1 truncate pl-5 text-[11px] text-muted-foreground">
                                            {task.progress_message}
                                        </p>
                                    ) : null}
                                    {task.output_preview ? (
                                        <pre className="mt-1 max-h-16 overflow-auto whitespace-pre-wrap break-words rounded bg-[#F8F7F4] p-1.5 pl-5 font-mono text-[10px] leading-relaxed text-[#6E6A60]">
                                            {task.output_preview}
                                        </pre>
                                    ) : null}
                                    {task.output_truncated ? (
                                        <p className="mt-1 pl-5 text-[10px] text-muted-foreground">
                                            {t("tasks.outputTruncated")}
                                        </p>
                                    ) : null}
                                </li>
                            ))}
                        </ul>
                    </div>
                ) : null}
            </div>
            <ConfirmDialog
                open={taskToCancel !== null}
                onOpenChange={(dialogOpen) => {
                    if (!dialogOpen) setTaskToCancel(null);
                }}
                title={t("tasks.stopConfirmTitle")}
                description={t("tasks.stopConfirmDescription", {
                    label: taskToCancel?.label ?? "",
                })}
                confirmLabel={t("tasks.stop")}
                onConfirm={confirmCancel}
            />
        </div>
    );
}
