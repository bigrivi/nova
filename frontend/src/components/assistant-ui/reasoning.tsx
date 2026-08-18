"use client";

import {
    MessagePartPrimitive,
    useAuiState,
    type MessagePartStatus,
    type ToolCallMessagePartStatus,
} from "@assistant-ui/react";
import {
    BrainIcon,
    CheckIcon,
    ChevronDownIcon,
    LoaderIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type FC, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

function formatTime(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${m}m ${s}s`;
}

function useElapsed(isActive: boolean): number | null {
    const startRef = useRef<number | null>(null);
    const [elapsed, setElapsed] = useState<number | null>(null);
    const finalizedRef = useRef(false);
    const prevActiveRef = useRef(isActive);

    if (startRef.current == null && isActive) {
        startRef.current = Date.now();
    }

    useEffect(() => {
        if (isActive && !prevActiveRef.current) {
            startRef.current = Date.now();
        } else if (
            !isActive &&
            prevActiveRef.current &&
            startRef.current != null
        ) {
            setElapsed(Date.now() - startRef.current);
            finalizedRef.current = true;
        }
        prevActiveRef.current = isActive;
    }, [isActive]);

    useEffect(() => {
        if (!isActive && startRef.current != null && !finalizedRef.current) {
            setElapsed(Date.now() - startRef.current);
            finalizedRef.current = true;
        }
    }, [isActive]);

    return elapsed;
}

export const ReasoningChainGroup = ({
    status,
    children,
}: {
    status?: MessagePartStatus | ToolCallMessagePartStatus;
    children: ReactNode;
}) => {
    const { t } = useTranslation();
    const chainActive = status?.type === "running";
    const [userOpen, setUserOpen] = useState<boolean | null>(null);

    const customMetadata = useAuiState((s) => s.message?.metadata?.custom);
    const messageRunning = useAuiState(
        (s) => s.message?.status?.type === "running",
    );
    const hasChainElapsed =
        customMetadata != null && "chainElapsedMs" in customMetadata;
    const metadataChainElapsedMs = hasChainElapsed
        ? ((customMetadata.chainElapsedMs as number | null | undefined) ?? null)
        : undefined;
    const chainElapsedMs = metadataChainElapsedMs;

    // Collapse only on message end; chainActive flips false between tools mid-loop and would flicker the group.
    const open = userOpen ?? messageRunning;

    return (
        <Collapsible
            open={open}
            onOpenChange={setUserOpen}
            className="mb-2 rounded-2xl border bg-muted/40"
        >
            <CollapsibleTrigger asChild>
                <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                >
                    <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                        <BrainIcon className="size-4" />
                        {chainActive
                            ? t("reasoning.thinking")
                            : chainElapsedMs != null
                              ? t("reasoning.workedFor", {
                                    time: formatTime(chainElapsedMs),
                                })
                              : t("reasoning.thoughtNoTime")}
                    </span>
                    <ChevronDownIcon
                        className={cn(
                            "size-4 text-muted-foreground transition-transform duration-200",
                            open && "rotate-180",
                        )}
                    />
                </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down">
                <div className="space-y-3 border-t px-4 py-3">{children}</div>
            </CollapsibleContent>
        </Collapsible>
    );
};

export const Reasoning: FC<{
    status?: MessagePartStatus | ToolCallMessagePartStatus;
}> = ({ status }) => {
    const { t } = useTranslation();
    const isActive = status?.type === "running";
    const elapsed = useElapsed(isActive);
    const [open, setOpen] = useState(true);

    const customMetadata = useAuiState((s) => s.message?.metadata?.custom);
    const hasReasoningElapsed =
        customMetadata != null && "reasoningElapsedMs" in customMetadata;
    const messageElapsedMs = hasReasoningElapsed
        ? ((customMetadata.reasoningElapsedMs as number | null | undefined) ??
          null)
        : undefined;
    const displayMs = elapsed ?? messageElapsedMs;

    return (
        <Collapsible open={open} onOpenChange={setOpen}>
            <CollapsibleTrigger asChild>
                <button
                    type="button"
                    className="flex w-full items-center justify-between gap-3 px-4 py-2 text-left"
                >
                    <span className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                        {isActive ? (
                            <LoaderIcon className="size-3.5 animate-spin" />
                        ) : (
                            <CheckIcon className="size-3.5 text-emerald-500" />
                        )}
                        {isActive
                            ? t("reasoning.thinking")
                            : displayMs != null
                              ? t("reasoning.thought", {
                                    time: formatTime(displayMs),
                                })
                              : t("reasoning.thoughtNoTime")}
                    </span>
                    <ChevronDownIcon
                        className={cn(
                            "size-4 text-muted-foreground transition-transform duration-200",
                            open && "rotate-180",
                        )}
                    />
                </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
                <div className="border-l-2 border-muted ml-3 pl-4 pb-3">
                    <MessagePartPrimitive.Text
                        component="div"
                        className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground"
                    />
                </div>
            </CollapsibleContent>
        </Collapsible>
    );
};

export const ThinkingIndicator: FC = () => {
    return (
        <div className="flex items-center gap-2 px-4 py-2 text-sm text-muted-foreground">
            <span className="inline-flex gap-0.5">
                <span
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
                    style={{ animationDelay: "0ms" }}
                />
                <span
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
                    style={{ animationDelay: "150ms" }}
                />
                <span
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
                    style={{ animationDelay: "300ms" }}
                />
            </span>
        </div>
    );
};
