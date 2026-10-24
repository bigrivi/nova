/** Modal frame for a screen that is still loading or has no data to show. */
import { useTheme } from "../../context/theme.tsx";

export function ScreenLoading({ message }: { message: string }) {
    const theme = useTheme();
    return (
        <box
            position="absolute"
            left="15%"
            right="15%"
            top="15%"
            paddingX={2}
            paddingY={2}
            border
            borderStyle="rounded"
            borderColor={theme.accent}
            backgroundColor={theme.surfaceDeep}
        >
            <text fg={theme.muted}>{message}</text>
        </box>
    );
}
