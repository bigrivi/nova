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

type ThreadScrollToBottomProps = {
    /**
     * Height reserved below the thread content for the composer overlay.
     * Keeps the button parked just above the composer while scrolling instead
     * of floating at whatever height the content happens to end at.
     */
    bottomOffset?: number;
};

export const ThreadScrollToBottom: FC<ThreadScrollToBottomProps> = ({
    bottomOffset = 0,
}) => {
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
        // mt-auto parks the row at the bottom of the min-h-full column while the
        // thread is shorter than the viewport; sticky takes over once it is
        // taller. Either way the button never lands mid-viewport.
        <div
            className={cn(
                "pointer-events-none sticky z-10 mt-auto flex w-full justify-center",
                !isVisible && "invisible",
            )}
            style={
                bottomOffset > 0 ? { bottom: `${bottomOffset}px` } : undefined
            }
        >
            {/* ScrollToBottom owns the click and disables itself at the bottom. */}
            <ThreadPrimitive.ScrollToBottom asChild>
                <TooltipIconButton
                    tooltip={t("thread.scrollToBottom")}
                    variant="outline"
                    className="pointer-events-auto rounded-full bg-background/95 p-3 shadow-sm backdrop-blur disabled:invisible"
                >
                    <ArrowDownIcon />
                </TooltipIconButton>
            </ThreadPrimitive.ScrollToBottom>
        </div>
    );
};
