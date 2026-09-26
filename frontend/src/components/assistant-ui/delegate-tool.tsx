"use client";

import {
    ToolFallbackContent,
    ToolFallbackResult,
    ToolFallbackRoot,
    ToolFallbackTrigger,
} from "@/components/assistant-ui/tool-fallback";
import { cn } from "@/lib/utils";
import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { memo, useMemo } from "react";
import { useTranslation } from "react-i18next";

const TASK_PREVIEW_LIMIT = 160;

function normalizeToolArgs(
    args: unknown,
    argsText?: string,
): Record<string, unknown> {
    if (args && typeof args === "object" && !Array.isArray(args)) {
        return args as Record<string, unknown>;
    }

    const text = String(argsText ?? "").trim();
    if (!text) {
        return {};
    }

    try {
        const parsed = JSON.parse(text);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : {};
    } catch {
        return {};
    }
}

function readStringField(
    args: Record<string, unknown>,
    field: string,
): string | null {
    const value = args[field];
    return typeof value === "string" && value.trim() ? value.trim() : null;
}

function truncateTask(task: string | null): string | null {
    if (!task) {
        return null;
    }
    const collapsed = task.replace(/\s+/g, " ").trim();
    if (!collapsed) {
        return null;
    }
    return collapsed.length > TASK_PREVIEW_LIMIT
        ? `${collapsed.slice(0, TASK_PREVIEW_LIMIT - 1)}…`
        : collapsed;
}

const DelegateToolImpl: ToolCallMessagePartComponent = ({
    args,
    argsText,
    result,
    status,
    isError,
}) => {
    const { t } = useTranslation();
    const normalizedArgs = useMemo(
        () => normalizeToolArgs(args, argsText),
        [args, argsText],
    );
    const target = readStringField(normalizedArgs, "target");
    const taskPreview = truncateTask(
        readStringField(normalizedArgs, "task"),
    );
    const isRunning = status?.type === "running";
    const isCancelled =
        status?.type === "incomplete" && status.reason === "cancelled";
    const errored = isError === true;

    const triggerLabel = target
        ? t("tools.delegatedTo", { target })
        : t("tools.delegateToAgent");

    return (
        <ToolFallbackRoot className={cn(errored && "opacity-80")}>
            <ToolFallbackTrigger
                toolName={triggerLabel}
                argsText={taskPreview ?? undefined}
                status={status}
                isError={isError}
            />
            <ToolFallbackContent>
                {taskPreview ? (
                    <p className="whitespace-pre-wrap break-words font-sans text-sm font-normal leading-6 text-slate-900">
                        {taskPreview}
                    </p>
                ) : null}
                {isRunning ? (
                    <p className="font-sans text-xs font-normal text-muted-foreground">
                        {t("tools.delegatedRunning")}
                    </p>
                ) : null}
                {!isRunning && !errored && !isCancelled ? (
                    <p className="font-sans text-xs font-normal text-muted-foreground">
                        {t("tools.delegatedPending")}
                    </p>
                ) : null}
                {!isRunning && !errored ? (
                    <ToolFallbackResult result={result} />
                ) : null}
            </ToolFallbackContent>
        </ToolFallbackRoot>
    );
};

export const DelegateTool = memo(
    DelegateToolImpl,
) as ToolCallMessagePartComponent;
