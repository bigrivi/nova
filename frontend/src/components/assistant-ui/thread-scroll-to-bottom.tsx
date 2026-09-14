import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { ThreadPrimitive } from "@assistant-ui/react";
import { ArrowDownIcon } from "lucide-react";
import { useEffect, useState, type FC } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

const VIEWPORT_SELECTOR = '[data-slot="aui_thread-viewport"]';

// assistant-ui's isAtBottom ignores style-only changes, so a composer that
// shrinks (todo panel, ask-user) would leave the button visible with nothing
// to scroll. Measure the geometry ourselves instead of trusting that flag.
function isScrolledAwayFromBottom(viewport: HTMLElement): boolean {
    const { scrollHeight, clientHeight, scrollTop } = viewport;
    if (scrollHeight <= clientHeight + 1) {
        return false;
    }
    return Math.abs(scrollHeight - scrollTop - clientHeight) > 1;
}

export const ThreadScrollToBottom: FC = () => {
    const { t } = useTranslation();
    const [isVisible, setIsVisible] = useState(false);

    useEffect(() => {
        const viewport = document.querySelector<HTMLElement>(VIEWPORT_SELECTOR);
        if (!viewport) {
            return;
        }
        const content = viewport.firstElementChild;
        const update = () => setIsVisible(isScrolledAwayFromBottom(viewport));

        update();
        viewport.addEventListener("scroll", update, { passive: true });
        const observer = new ResizeObserver(update);
        observer.observe(viewport);
        if (content) {
            observer.observe(content);
        }

        return () => {
            viewport.removeEventListener("scroll", update);
            observer.disconnect();
        };
    }, []);

    return (
        // Floats above the footer, which is its sticky, positioned ancestor.
        <ThreadPrimitive.ScrollToBottom asChild>
            <TooltipIconButton
                tooltip={t("thread.scrollToBottom")}
                variant="outline"
                className={cn(
                    "pointer-events-auto absolute -top-10 z-10 self-center rounded-full bg-background/95 p-3 shadow-sm backdrop-blur disabled:invisible",
                    !isVisible && "invisible",
                )}
            >
                <ArrowDownIcon />
            </TooltipIconButton>
        </ThreadPrimitive.ScrollToBottom>
    );
};
