import { useRef } from "react";
import { useTheme } from "../context/theme.tsx";
import { useScreenStore } from "../stores/screen-store.ts";
import type { TuiMessage } from "../stores/chat-store.ts";

export function UserMessage({ message }: { message: TuiMessage }) {
    const theme = useTheme();
    const part = message.parts[0]?.type === "text" ? message.parts[0] : undefined;
    const text = part?.text ?? "";
    const images = part?.images ?? [];
    // A click (no drag) opens the message's actions; a drag is a text
    // selection, which already copied itself on mouseup.
    const dragged = useRef(false);

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
            onMouseDown={() => {
                dragged.current = false;
            }}
            onMouseMove={() => {
                dragged.current = true;
            }}
            onMouseUp={(event) => {
                if (event.button !== 0) return;
                if (dragged.current) return;
                useScreenStore.getState().open({
                    kind: "message-actions",
                    messageId: message.id,
                    text,
                });
            }}
        >
            <box flexDirection="row" gap={1}>
                <text fg={theme.primary.muted} content=">" />
                <box flexGrow={1} flexDirection="column">
                    <text fg={theme.text.base} content={text} />
                    {images.map((name, index) => (
                        <text
                            key={`${name}:${index}`}
                            fg={theme.primary.muted}
                            content={`▧ ${name}`}
                        />
                    ))}
                </box>
            </box>
        </box>
    );
}
