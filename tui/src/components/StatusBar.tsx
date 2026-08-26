/** Bottom status bar: model info + running status */
import { useChatStore } from "../stores/chat-store.ts";
import { theme } from "../theme.ts";

export function StatusBar() {
    const isStreaming = useChatStore((state) => state.isStreaming);
    const provider = useChatStore((state) => state.provider);
    const model = useChatStore((state) => state.model);

    return (
        <box paddingX={2} paddingY={0} marginTop={0} flexShrink={0}>
            <text fg={isStreaming ? theme.running : theme.muted}>
                {isStreaming ? "●" : "○"} {provider}/{model}
            </text>
        </box>
    );
}
