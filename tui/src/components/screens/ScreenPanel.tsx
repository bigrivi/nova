/** Centered modal panel: the content decides the height, the terminal decides
 *  the position — it sits in the middle at any terminal size. */
import type { ReactNode } from "react";
import { useTheme } from "../../context/theme.tsx";

export function ScreenPanel({
    children,
    width = "50%",
}: {
    children: ReactNode;
    width?: `${number}%`;
}) {
    const theme = useTheme();
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
            {/* `surface` is one step above `background` in every theme, so the
                panel reads as a raised block without needing a border. */}
            <box
                width={width}
                paddingX={2}
                paddingY={2}
                backgroundColor={theme.surface}
            >
                {children}
            </box>
        </box>
    );
}
