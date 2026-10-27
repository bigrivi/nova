import { useToastStore } from "../stores/toast-store.ts";
import { useTheme } from "../context/theme.tsx";

export function Toast() {
    const theme = useTheme();
    const message = useToastStore((s) => s.message);
    if (!message) return null;
    return (
        <box position="absolute" bottom={2} right={2} flexShrink={0}>
            <box
                paddingX={2}
                paddingY={1}
                border
                borderStyle="rounded"
                borderColor={theme.feedback.success}
                backgroundColor={theme.background.base}
            >
                <text fg={theme.feedback.success} content={`✓ ${message}`} />
            </box>
        </box>
    );
}
