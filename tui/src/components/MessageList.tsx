/** Message list: ScrollBox virtual scrolling + role routing */
import { useChatStore } from "../stores/chat-store.ts";
import { AssistantMessage } from "./AssistantMessage.tsx";
import { Banner } from "./Banner.tsx";
import { CompactionBanner } from "./parts/CompactionBanner.tsx";
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
            <box paddingX={1} paddingTop={1}>
                <Banner />
            </box>
            {messages.map((msg) =>
                msg.role === "user" ? (
                    <UserMessage key={msg.id} message={msg} />
                ) : (
                    <AssistantMessage key={msg.id} message={msg} />
                ),
            )}
            <CompactionBanner />
        </scrollbox>
    );
}
