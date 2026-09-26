import { useReasoningStore } from "@/stores/reasoning-store";
import { type FC, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

/**
 * In-progress view of context compaction.
 *
 * The summary streams in as the model writes it, so the user can see what is
 * being remembered instead of watching a spinner. The durable version of the
 * same text is the summary message the backend writes when compaction finishes.
 */
export const CompactionBanner: FC = () => {
    const { t } = useTranslation();
    const compacting = useReasoningStore((s) => s.compacting);
    const summary = useReasoningStore((s) => s.compactionSummary);
    const scrollRef = useRef<HTMLPreElement>(null);

    useEffect(() => {
        const element = scrollRef.current;
        if (element) {
            element.scrollTop = element.scrollHeight;
        }
    }, [summary]);

    if (!compacting) return null;

    return (
        <div className="px-1 py-1.5 text-xs text-muted-foreground/60">
            <div className="flex items-center gap-2">
                <span className="inline-flex gap-0.5">
                    <span
                        className="size-1 animate-bounce rounded-full bg-muted-foreground/60"
                        style={{ animationDelay: "0ms" }}
                    />
                    <span
                        className="size-1 animate-bounce rounded-full bg-muted-foreground/60"
                        style={{ animationDelay: "150ms" }}
                    />
                    <span
                        className="size-1 animate-bounce rounded-full bg-muted-foreground/60"
                        style={{ animationDelay: "300ms" }}
                    />
                </span>
                {t("reasoning.compacting")}
            </div>
            {summary ? (
                <pre
                    ref={scrollRef}
                    data-slot="compaction-summary"
                    className="mt-1.5 max-h-40 overflow-y-auto overscroll-contain whitespace-pre-wrap break-words rounded-md border border-dashed border-[#E4E1D9] bg-[#F8F7F4] p-2 font-mono text-[11px] leading-relaxed text-[#6E6A60]"
                >
                    {summary}
                </pre>
            ) : null}
        </div>
    );
};
