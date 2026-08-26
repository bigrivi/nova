import type { TuiMessage } from "../stores/chat-store.ts";
import { theme } from "../theme.ts";

export function UserMessage({ message }: { message: TuiMessage }) {
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
            <text content={text} />
        </box>
    );
}
