import { useTheme } from "../context/theme.tsx";
import type { TuiMessage } from "../stores/chat-store.ts";

export function UserMessage({ message }: { message: TuiMessage }) {
    const theme = useTheme();
    const text = message.parts[0]?.type === "text" ? message.parts[0].text : "";
    return (
        <box
            flexDirection="column"
            paddingX={2}
            paddingTop={1}
            paddingBottom={1}
            marginTop={1}
            minHeight={3}
            justifyContent="center"
            backgroundColor={theme.background.raised}
        >
            <box flexDirection="row" gap={1}>
                <text fg={theme.primary.muted} content=">" />
                <box flexGrow={1}>
                    <text fg={theme.text.base} content={text} />
                </box>
            </box>
        </box>
    );
}
