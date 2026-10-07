"use client";

import { useAuiState } from "@assistant-ui/react";
import { ChevronDownIcon, WrenchIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

export const ToolGroup = ({
    children,
    count,
    erroredCount = 0,
    variant = "standalone",
}: {
    children: ReactNode;
    count: number;
    erroredCount?: number;
    variant?: "timeline" | "standalone";
}) => {
    const { t } = useTranslation();
    // null means nobody has touched this card yet, so it follows the turn and
    // collapses with the rest of the message. A manual choice wins from then
    // on, otherwise reading a result would yank it shut mid-turn.
    const [userOpen, setUserOpen] = useState<boolean | null>(null);
    const messageRunning = useAuiState(
        (s) => s.message?.status?.type === "running",
    );
    const open = userOpen ?? messageRunning;

    if (count === 0) return null;

    const inTimeline = variant === "timeline";
    // A collapsed card hides its rows, so the header has to carry the failure.
    const errored = erroredCount > 0;

    return (
        <div
            className={cn(
                "relative min-w-0 max-w-full",
                inTimeline ? "mb-[18px] last:mb-0" : "my-1",
            )}
        >
            {inTimeline ? (
                <span
                    aria-hidden="true"
                    className="absolute -left-[22px] top-[5px] size-[9px] rounded-[3px] border-2 border-brand bg-card"
                />
            ) : null}
            <Collapsible
                open={open}
                onOpenChange={setUserOpen}
                data-slot="tool-group"
                className={cn(
                    "max-w-full overflow-hidden rounded-[10px] border bg-card",
                    errored ? "border-danger/40" : "border-border",
                )}
            >
                <CollapsibleTrigger asChild>
                    <button
                        type="button"
                        className={cn(
                            "flex w-full items-center gap-[7px] px-3 py-[9px] text-left",
                            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30 focus-visible:ring-inset motion-reduce:transition-none",
                            // The rule separates header from rows, so it only
                            // exists while there are rows below the header.
                            open && "border-b border-border",
                            errored
                                ? "bg-danger-soft hover:bg-danger-soft/80"
                                : "bg-brand-soft hover:bg-brand-soft/80",
                        )}
                    >
                        <WrenchIcon
                            className={cn(
                                "size-[14px] shrink-0",
                                errored ? "text-danger" : "text-brand",
                            )}
                            aria-hidden="true"
                        />
                        <span
                            className={cn(
                                "text-[12.5px] font-semibold",
                                errored ? "text-danger" : "text-brand",
                            )}
                        >
                            {t("tools.toolCalls")}
                        </span>
                        <span className="ml-auto flex items-center gap-[7px]">
                            <span className="font-mono text-[11.5px] text-weak">
                                {count}
                            </span>
                            <ChevronDownIcon
                                className={cn(
                                    "size-[14px] shrink-0 text-weak transition-transform duration-200 motion-reduce:transition-none",
                                    open && "rotate-180",
                                )}
                                aria-hidden="true"
                            />
                        </span>
                    </button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                    <div className="divide-y divide-border">{children}</div>
                </CollapsibleContent>
            </Collapsible>
        </div>
    );
};