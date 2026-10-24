import type { TuiMessage } from "../stores/chat-store.ts";
import { useTheme } from "../context/theme.tsx";

export function UserMessage({ message }: { message: TuiMessage }) {
    const theme = useTheme();
    const text = message.parts[0]?.type === "text" ? message.parts[0].text : "";
    return (
        <box
            flexDirection="column"
            paddingX={2}
            paddingTop={1}
            paddingBottom={1}
            marginBottom={1}
            minHeight={3}
            justifyContent="center"
            backgroundColor={theme.surface}
        >
            <box flexDirection="row" gap={1}>
                <text fg={theme.accent} content=">" />
                <box flexGrow={1}>
                    <text content={text} />
                </box>
            </box>
        </box>
    );
}
