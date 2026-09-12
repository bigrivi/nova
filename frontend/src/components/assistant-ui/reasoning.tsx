"use client";

import {
    MessagePartPrimitive,
    useAuiState,
    type MessagePartStatus,
    type ToolCallMessagePartStatus,
} from "@assistant-ui/react";
import { BrainIcon, ChevronDownIcon } from "lucide-react";
import {
    createContext,
    useContext,
    useState,
    type FC,
    type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const InTimelineContext = createContext(false);

function formatTime(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return `${m}m ${s}s`;
}

export const ReasoningChainGroup = ({
    status,
    toolCount,
    elapsedMs = null,
    children,
}: {
    status?: MessagePartStatus | ToolCallMessagePartStatus;
    toolCount?: number;
    elapsedMs?: number | null;
    children: ReactNode;
}) => {
    const { t } = useTranslation();
    const chainActive = status?.type === "running";
    const [userOpen, setUserOpen] = useState<boolean | null>(null);

    const messageRunning = useAuiState(
        (s) => s.message?.status?.type === "running",
    );

    // Collapse only on message end; chainActive flips false between tools mid-loop and would flicker the group.
    const open = userOpen ?? messageRunning;

    const visibleToolCount = toolCount ?? 0;
    const chainElapsedMs = elapsedMs;

    let headerLabel: string;
    let headerSub: string | null = null;
    if (chainActive) {
        headerLabel = t("reasoning.thinking");
    } else if (chainElapsedMs != null) {
        headerLabel = t("reasoning.workedFor", {
            time: formatTime(chainElapsedMs),
        });
    } else {
        headerLabel = t("reasoning.thoughtNoTime");
    }

    if (!chainActive && visibleToolCount > 0) {
        const toolsCount = t("reasoning.toolsCount", { count: visibleToolCount });
        headerSub =
            toolsCount === "reasoning.toolsCount"
                ? `· ${visibleToolCount} tool calls`
                : toolsCount;
    }

    return (
        <Collapsible
            open={open}
            onOpenChange={setUserOpen}
            className="mb-2 max-w-full overflow-hidden rounded-[10px] border border-[#E4E1D9] bg-white"
        >
            <CollapsibleTrigger asChild>
                <button
                    type="button"
                    className="flex w-full items-center gap-2 px-[13px] py-[11px] text-left hover:bg-[#FAFAF8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6E56CF]/30 focus-visible:ring-inset"
                >
                    <span className="flex items-center gap-2 text-[13px] font-medium text-[#1C1B18]">
                        <BrainIcon
                            className="size-4 shrink-0 text-[#6E56CF]"
                            aria-hidden="true"
                        />
                        <span className={cn(chainActive && "text-[#6E56CF]")}>
                            {headerLabel}
                        </span>
                        {headerSub ? (
                            <span className="font-normal text-[#9C978A]">
                                {headerSub}
                            </span>
                        ) : null}
                    </span>
                    <span className="ml-auto flex items-center">
                        <ChevronDownIcon
                            className={cn(
                                "size-4 shrink-0 text-[#9C978A] transition-transform duration-200 motion-reduce:transition-none",
                                open && "rotate-180",
                            )}
                            aria-hidden="true"
                        />
                    </span>
                </button>
            </CollapsibleTrigger>
            <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down motion-reduce:data-[state=closed]:animate-none motion-reduce:data-[state=open]:animate-none">
                <div className="min-w-0 border-t border-[#E4E1D9] bg-[#FDFCFA] px-[14px] pb-4 pt-4">
                    <div className="relative min-w-0 pl-[22px] before:absolute before:bottom-[6px] before:left-[5px] before:top-[6px] before:w-px before:bg-[#D3CFC4] before:content-['']">
                        <InTimelineContext.Provider value={true}>
                            {children}
                        </InTimelineContext.Provider>
                    </div>
                </div>
            </CollapsibleContent>
        </Collapsible>
    );
};

export const Reasoning: FC<{ elapsedMs?: number | null }> = ({
    elapsedMs = null,
}) => {
    const { t } = useTranslation();
    const inTimeline = useContext(InTimelineContext);
    const [open, setOpen] = useState(true);

    return (
        <div
            className={cn(
                "relative mb-[18px] min-w-0 last:mb-0",
                !inTimeline && "pl-[22px]",
            )}
        >
            <span
                aria-hidden="true"
                className={cn(
                    "absolute top-[6px] size-[9px] rounded-full border-2 border-[#6E56CF] bg-white",
                    inTimeline ? "-left-[22px]" : "left-0",
                )}
            />
            <Collapsible open={open} onOpenChange={setOpen}>
                <CollapsibleTrigger asChild>
                    <button
                        type="button"
                        className="flex w-full items-center gap-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#6E56CF]/25 focus-visible:ring-inset"
                    >
                        <span className="text-[12.5px] font-semibold text-[#6E56CF]">
                            {t("reasoning.thinkingTag")}
                        </span>
                        {elapsedMs != null ? (
                            <span className="text-[12px] font-normal text-[#9C978A]">
                                · {formatTime(elapsedMs)}
                            </span>
                        ) : null}
                        <ChevronDownIcon
                            className={cn(
                                "size-3.5 shrink-0 text-[#9C978A] transition-transform duration-200 motion-reduce:transition-none",
                                open && "rotate-180",
                            )}
                            aria-hidden="true"
                        />
                    </button>
                </CollapsibleTrigger>
                <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down motion-reduce:data-[state=closed]:animate-none motion-reduce:data-[state=open]:animate-none">
                    <div className="min-w-0 break-words pt-1 text-[14px] leading-[1.75] text-[#6E6A60]">
                        <MessagePartPrimitive.Text
                            component="div"
                            className="whitespace-pre-wrap break-words"
                        />
                    </div>
                </CollapsibleContent>
            </Collapsible>
        </div>
    );
};

export const ThinkingIndicator: FC = () => {
    return (
        <div className="flex min-w-0 items-center gap-2 py-1 text-sm text-muted-foreground">
            <span className="inline-flex gap-0.5" aria-hidden="true">
                <span
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground motion-reduce:animate-none"
                    style={{ animationDelay: "0ms" }}
                />
                <span
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground motion-reduce:animate-none"
                    style={{ animationDelay: "150ms" }}
                />
                <span
                    className="size-1.5 animate-bounce rounded-full bg-muted-foreground motion-reduce:animate-none"
                    style={{ animationDelay: "300ms" }}
                />
            </span>
        </div>
    );
};
