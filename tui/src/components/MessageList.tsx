/** Message list: ScrollBox virtual scrolling + role routing */
import { useChatStore } from "../stores/chat-store.ts";
import { AssistantMessage } from "./AssistantMessage.tsx";
import { UserMessage } from "./UserMessage.tsx";

export function MessageList() {
    const messages = useChatStore((state) => state.messages);

    return (
        <scrollbox
            flexGrow={1}
            scrollY
            stickyScroll
            stickyStart="bottom"
            viewportCulling
        >
            {messages.map((msg) =>
                msg.role === "user" ? (
                    <UserMessage key={msg.id} message={msg} />
                ) : (
                    <AssistantMessage key={msg.id} message={msg} />
                ),
            )}
        </scrollbox>
    );
}
