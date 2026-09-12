"use client";

import { WrenchIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

export const ToolGroup = ({
    children,
    count,
    variant = "standalone",
}: {
    children: ReactNode;
    count: number;
    variant?: "timeline" | "standalone";
}) => {
    const { t } = useTranslation();

    if (count === 0) return null;

    const inTimeline = variant === "timeline";

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
                    className="absolute -left-[22px] top-[5px] size-[9px] rounded-[3px] border-2 border-[#1D5FA8] bg-white"
                />
            ) : null}
            <div className="max-w-full overflow-hidden rounded-[10px] border border-[#E4E1D9] bg-white">
                <div className="flex items-center gap-[7px] border-b border-[#E4E1D9] bg-[#F0F5FB] px-3 py-[9px]">
                    <WrenchIcon
                        className="size-[14px] shrink-0 text-[#1D5FA8]"
                        aria-hidden="true"
                    />
                    <span className="text-[12.5px] font-semibold text-[#1D5FA8]">
                        {t("tools.toolCalls")}
                    </span>
                    <span className="ml-auto font-mono text-[11.5px] text-[#9C978A]">
                        {count}
                    </span>
                </div>
                <div className="divide-y divide-[#E4E1D9]">{children}</div>
            </div>
        </div>
    );
};
