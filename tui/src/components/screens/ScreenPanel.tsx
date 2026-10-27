/** Centered modal panel: the content decides the height, the terminal decides
 *  the position — it sits in the middle at any terminal size. */
import type { ReactNode } from "react";
import { useTheme } from "../../context/theme.tsx";

export function ScreenPanel({
    children,
    width = "50%",
    border = false,
}: {
    children: ReactNode;
    width?: `${number}%`;
    border?: boolean;
}) {
    const theme = useTheme();
    // BoxRenderable turns the border on whenever borderStyle/borderColor is
    // passed, so the border props must be absent, not merely falsy.
    const frame = border
        ? { border: true, borderStyle: "rounded" as const, borderColor: theme.accent }
        : {};
    return (
        <box
            position="absolute"
            left={0}
            right={0}
            top={0}
            bottom={0}
            justifyContent="center"
            alignItems="center"
        >
            <box
                width={width}
                paddingX={2}
                paddingY={2}
                backgroundColor={theme.surfaceDeep}
                {...frame}
            >
                {children}
            </box>
        </box>
    );
}
