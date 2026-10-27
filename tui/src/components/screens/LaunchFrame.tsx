/** Frame around the composer while the launch screen is active: a rounded border
 *  that slowly breathes between the plain border colour and the accent.
 *
 *  It owns the timer instead of the screen so the composer underneath keeps its
 *  identity — a re-render every tick would otherwise reach the textarea. */
import { useEffect, useState, type ReactNode } from "react";
import { useTheme } from "../../context/theme.tsx";
import { mixColor } from "../../themes/color.ts";
import { breath, motionEnabled, TICK_MS } from "./launch.ts";

/** Terminal width of the launch card, as a share of the screen. */
const CARD_WIDTH = "60%";
/** Hard cap so the card does not stretch into a band on very wide terminals. */
const CARD_MAX_WIDTH = 76;

export function LaunchFrame({
    active,
    children,
}: {
    active: boolean;
    children: ReactNode;
}) {
    const theme = useTheme();
    const [tick, setTick] = useState(0);
    const animate = active && motionEnabled(process.env);

    useEffect(() => {
        if (!animate) return;
        const timer = setInterval(() => {
            setTick((value) => value + 1);
        }, TICK_MS);
        return () => {
            clearInterval(timer);
        };
    }, [animate]);

    // BoxRenderable turns the border on as soon as borderStyle is present, so
    // the border props must be absent rather than falsy when inactive.
    const frame = active
        ? {
              border: true as const,
              borderStyle: "rounded" as const,
              borderColor: animate
                  ? mixColor(theme.border, theme.accent, breath(tick) * 0.7)
                  : theme.border,
          }
        : {};

    return (
        <box
            width={active ? CARD_WIDTH : "100%"}
            maxWidth={active ? CARD_MAX_WIDTH : undefined}
            flexDirection="column"
            {...frame}
        >
            {children}
        </box>
    );
}
