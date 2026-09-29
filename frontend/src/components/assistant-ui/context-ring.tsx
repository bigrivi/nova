import { useTranslation } from "react-i18next";

import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ContextUsage } from "../../stores/context-usage-store";

/** Compact token counts the way agent UIs do: 49.5K, 1.2M. */
function formatTokenCount(value: number): string {
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}M`;
    }
    if (value >= 1_000) {
        return `${(value / 1_000).toFixed(1)}K`;
    }
    return String(Math.max(0, Math.round(value)));
}

const CONTEXT_WARN_PERCENT = 85;
const RING_RADIUS = 9;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * WorkBuddy-style context ring: a small progress circle in the composer
 * footer, left of the model selector. The detail line only appears on hover
 * so the footer stays quiet; at or past the warn threshold the arc turns
 * the danger color.
 */
export function ContextRing({ usage }: { usage: ContextUsage }) {
    const { t } = useTranslation();
    const ratio =
        usage.limit > 0
            ? Math.min(1, Math.max(0, usage.used / usage.limit))
            : 0;
    const detail = `${(ratio * 100).toFixed(1)}% · ${formatTokenCount(usage.used)} / ${formatTokenCount(usage.limit)} ${t("composer.contextUsed")}`;
    const warn = usage.percent >= CONTEXT_WARN_PERCENT;

    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <span
                    role="img"
                    aria-label={detail}
                    className={cn(
                        "inline-flex size-7 shrink-0 items-center justify-center rounded-full",
                        warn ? "text-danger" : "text-weak-strong",
                    )}
                >
                    <svg
                        width="22"
                        height="22"
                        viewBox="0 0 22 22"
                        aria-hidden="true"
                        className="-rotate-90"
                    >
                        <circle
                            cx="11"
                            cy="11"
                            r={RING_RADIUS}
                            fill="none"
                            strokeWidth="2.5"
                            className="stroke-border"
                        />
                        <circle
                            cx="11"
                            cy="11"
                            r={RING_RADIUS}
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            strokeLinecap="round"
                            strokeDasharray={RING_CIRCUMFERENCE}
                            strokeDashoffset={
                                RING_CIRCUMFERENCE * (1 - ratio)
                            }
                        />
                    </svg>
                </span>
            </TooltipTrigger>
            <TooltipContent side="top">
                <span className="tabular-nums">{detail}</span>
            </TooltipContent>
        </Tooltip>
    );
}
