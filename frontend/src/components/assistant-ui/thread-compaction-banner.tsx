import { useReasoningStore } from "@/stores/reasoning-store";
import { type FC } from "react";
import { useTranslation } from "react-i18next";

export const CompactionBanner: FC = () => {
    const { t } = useTranslation();
    const compacting = useReasoningStore((s) => s.compacting);

    if (!compacting) return null;

    return (
        <div className="flex items-center gap-2 px-1 py-1.5 text-xs text-muted-foreground/60">
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
    );
};
