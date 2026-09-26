import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import { revealDurationSeconds } from "@/lib/reveal-timing";
import { cn } from "@/lib/utils";

/**
 * Render text that is clipped to its row, and reveal the rest when the row is
 * hovered.
 *
 * The trigger is the whole row, not the label: the reveal is armed by the row's
 * `group/thread` named group, so hovering the row's padding, the icon gutter or
 * the row actions button all start it. Whatever renders this has to sit inside
 * an element carrying that group.
 *
 * The overflow check keeps short titles still: the reveal animation walks the
 * text to its tail, so running it on a title that already fits would nudge a
 * perfectly readable label sideways for no reason.
 *
 * The same measurement feeds both the travel distance and the duration, so the
 * text always moves at the same speed regardless of how long the title is.
 */
export function HoverScrollText({
    text,
    className,
}: {
    text: string;
    className?: string;
}) {
    const wrapperRef = useRef<HTMLSpanElement>(null);
    const [overflowPx, setOverflowPx] = useState(0);

    useLayoutEffect(() => {
        const element = wrapperRef.current;
        if (!element) {
            return;
        }
        const overflow = element.scrollWidth - element.clientWidth;
        setOverflowPx((previous) => (previous === overflow ? previous : overflow));
    }, [text]);

    const overflows = overflowPx > 0;

    return (
        <span
            ref={wrapperRef}
            className={cn("min-w-0 flex-1 overflow-hidden", className)}
        >
            <span
                className={cn(
                    "block w-max whitespace-nowrap",
                    overflows &&
                        "motion-safe:group-hover/thread:animate-[title-reveal_linear_forwards]",
                )}
                style={
                    overflows
                        ? ({
                              "--reveal-distance": `-${overflowPx}px`,
                              animationDuration: `${revealDurationSeconds(overflowPx)}s`,
                          } as CSSProperties)
                        : undefined
                }
            >
                {text}
            </span>
        </span>
    );
}
