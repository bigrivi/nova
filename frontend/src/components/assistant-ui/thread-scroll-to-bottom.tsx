import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { useAuiState } from "@assistant-ui/react";
import { ArrowDownIcon } from "lucide-react";
import { useEffect, useState, type FC } from "react";
import { useTranslation } from "react-i18next";

const SCROLL_TO_BOTTOM_THRESHOLD = 32;

export const ThreadScrollToBottom: FC = () => {
    const { t } = useTranslation();
    const isEmpty = useAuiState((s) => s.thread.isEmpty);
    const [isVisible, setIsVisible] = useState(false);

    useEffect(() => {
        const viewport = document.querySelector<HTMLElement>(
            '[data-slot="aui_thread-viewport"]',
        );
        if (!viewport) {
            setIsVisible(false);
            return;
        }

        const updateVisibility = () => {
            const distanceToBottom =
                viewport.scrollHeight -
                (viewport.scrollTop + viewport.clientHeight);
            setIsVisible(distanceToBottom > SCROLL_TO_BOTTOM_THRESHOLD);
        };

        updateVisibility();
        viewport.addEventListener("scroll", updateVisibility, {
            passive: true,
        });
        window.addEventListener("resize", updateVisibility);

        return () => {
            viewport.removeEventListener("scroll", updateVisibility);
            window.removeEventListener("resize", updateVisibility);
        };
    }, []);

    if (isEmpty || !isVisible) {
        return null;
    }

    return (
        <div className="pointer-events-none sticky bottom-28 z-10 flex overflow-visible pb-4 md:bottom-32 md:pb-6">
            <TooltipIconButton
                tooltip={t("thread.scrollToBottom")}
                variant="outline"
                className="pointer-events-auto absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full bg-background/95 p-3 shadow-sm backdrop-blur"
                onClick={() => {
                    const viewport = document.querySelector<HTMLElement>(
                        '[data-slot="aui_thread-viewport"]',
                    );
                    viewport?.scrollTo({
                        top: viewport.scrollHeight,
                        behavior: "smooth",
                    });
                }}
            >
                <ArrowDownIcon />
            </TooltipIconButton>
        </div>
    );
};
