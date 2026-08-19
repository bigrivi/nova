"use client";

import {
    CheckCircle2Icon,
    ChevronDownIcon,
    CircleIcon,
    Loader2Icon,
    XCircleIcon,
} from "lucide-react";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";
import {
    type TodoStatus,
    useTodoStore,
} from "@/stores/todo-store";

function normalizeStatus(status: string | undefined): TodoStatus {
    if (
        status === "in_progress" ||
        status === "completed" ||
        status === "cancelled"
    ) {
        return status;
    }
    return "pending";
}

const StatusIcon = ({ status }: { status: TodoStatus }) => {
    switch (status) {
        case "completed":
            return (
                <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
            );
        case "in_progress":
            return (
                <Loader2Icon className="size-4 shrink-0 animate-spin text-sky-500" />
            );
        case "cancelled":
            return (
                <XCircleIcon className="size-4 shrink-0 text-muted-foreground/50" />
            );
        default:
            return (
                <CircleIcon className="size-4 shrink-0 text-muted-foreground/50" />
            );
    }
};

const TodoProgressPanelImpl = () => {
    const { t } = useTranslation();
    const active = useTodoStore((s) => s.active);
    const [open, setOpen] = useState(() =>
        (active?.todos ?? []).some((item) => item.status === "in_progress"),
    );

    const todos = (active?.todos ?? []).map((item) => ({
        ...item,
        status: normalizeStatus(item.status),
    }));

    const total = todos.length;
    const completedCount = todos.filter(
        (t) => t.status === "completed",
    ).length;
    const cancelledCount = todos.filter(
        (t) => t.status === "cancelled",
    ).length;
    const inProgress = todos.find((t) => t.status === "in_progress");
    const lastCompleted = [...todos]
        .reverse()
        .find((t) => t.status === "completed");
    const allDone = total > 0 && completedCount + cancelledCount === total;

    if (!active || total === 0) return null;

    const summaryText =
        inProgress?.content ??
        lastCompleted?.content ??
        t("tools.todoProgress");

    return (
        <div className="w-full rounded-lg border bg-background shadow-sm">
            <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                className="flex w-full items-center gap-2.5 px-4 py-2.5 text-sm hover:bg-muted/50"
            >
                {inProgress && !allDone ? (
                    <Loader2Icon className="size-4 shrink-0 animate-spin text-sky-500" />
                ) : allDone ? (
                    <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
                ) : (
                    <CircleIcon className="size-4 shrink-0 text-muted-foreground/60" />
                )}

                <span className="min-w-0 flex-1 truncate text-start leading-none">
                    {summaryText}
                </span>

                {total > 0 && (
                    <span
                        className={cn(
                            "shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
                            allDone
                                ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                                : "bg-muted text-muted-foreground",
                        )}
                    >
                        {completedCount}/{total}
                    </span>
                )}

                <ChevronDownIcon
                    className={cn(
                        "size-4 shrink-0 text-muted-foreground transition-transform duration-200",
                        open && "rotate-180",
                    )}
                />
            </button>

            {open && (
                <div className="border-t px-4 pb-2.5 pt-2">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {t("tools.todoProgress")}
                    </div>
                    <ul className="mt-1.5 space-y-1.5">
                        {todos.map((todo, index) => (
                            <li
                                key={index}
                                className="flex items-center gap-2 text-sm"
                            >
                                <StatusIcon status={todo.status} />
                                <span
                                    className={cn(
                                        "min-w-0",
                                        todo.status === "cancelled" &&
                                            "text-muted-foreground line-through",
                                        todo.status === "in_progress" &&
                                            "font-medium",
                                    )}
                                >
                                    {todo.content}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    );
};

export const TodoProgressPanel = memo(TodoProgressPanelImpl);