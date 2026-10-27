/** Modal frame for a screen that is still loading or has no data to show. */
import { useTheme } from "../../context/theme.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";

export function ScreenLoading({ message }: { message: string }) {
    const theme = useTheme();
    return (
        <ScreenPanel>
            <text fg={theme.muted}>{message}</text>
        </ScreenPanel>
    );
}
