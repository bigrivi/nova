/** Bottom status bar: model info + running status */
import { useChatStore } from "../stores/chat-store.ts";

export function StatusBar() {
    const isStreaming = useChatStore((state) => state.isStreaming);
    const provider = useChatStore((state) => state.provider);
    const model = useChatStore((state) => state.model);

    return (
        <box paddingX={2} flexShrink={0}>
            <text fg={isStreaming ? "#d29922" : "#6e7681"}>
                {isStreaming ? "●" : "○"} {provider}/{model}
            </text>
        </box>
    );
}
