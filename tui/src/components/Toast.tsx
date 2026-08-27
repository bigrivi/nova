import { useToastStore } from "../stores/toast-store.ts";
import { theme } from "../theme.ts";

export function Toast() {
    const message = useToastStore((s) => s.message);
    if (!message) return null;
    return (
        <box position="absolute" bottom={2} right={2} flexShrink={0}>
            <box
                paddingX={2}
                paddingY={1}
                border
                borderStyle="rounded"
                borderColor={theme.success}
                backgroundColor={theme.surfaceDeep}
            >
                <text fg={theme.success} content={`✓ ${message}`} />
            </box>
        </box>
    );
}
