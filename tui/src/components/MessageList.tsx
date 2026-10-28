/** Message list: ScrollBox virtual scrolling + role routing */
import type { ScrollBoxRenderable } from "@opentui/core";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "../context/theme.tsx";
import { useChatStore } from "../stores/chat-store.ts";
import { AssistantMessage } from "./AssistantMessage.tsx";
import { Banner } from "./Banner.tsx";
import { CompactionBanner } from "./parts/CompactionBanner.tsx";
import { SubagentNotice } from "./SubagentNotice.tsx";
import { UserMessage } from "./UserMessage.tsx";

/** Stable identity: a fresh object each render would re-apply the options. */
const HIDDEN_SCROLLBAR = { visible: false } as const;

export function MessageList() {
    const messages = useChatStore((state) => state.messages);
    const theme = useTheme();
    const scrollRef = useRef<ScrollBoxRenderable>(null);
    const [atBottom, setAtBottom] = useState(true);

    // The scrollbar is the only thing that reports a position change, and the
    // scrollbox replaces its `onChange` option, so listen to the bar's event.
    useEffect(() => {
        const bar = scrollRef.current?.verticalScrollBar;
        if (!bar) return;
        const track = (): void => {
            const box = scrollRef.current;
            if (!box) return;
            const max = Math.max(0, box.scrollHeight - box.viewport.height);
            // Sticky scrolling parks the viewport exactly at max; one row up
            // is already "away", which is why the slack is zero.
            const next = box.scrollTop >= max;
            setAtBottom((current) => (current === next ? current : next));
        };
        bar.on("change", track);
        return () => {
            bar.off("change", track);
        };
    }, []);

    const jumpToLatest = (): void => {
        const box = scrollRef.current;
        if (!box) return;
        box.scrollTop = box.scrollHeight;
        // Re-arm auto-follow for the next streamed message.
        box.stickyScroll = true;
        setAtBottom(true);
    };

    return (
        <box flexGrow={1} flexDirection="column">
            <scrollbox
                ref={scrollRef}
                flexGrow={1}
                scrollY
                stickyScroll
                stickyStart="bottom"
                viewportCulling
                scrollbarOptions={HIDDEN_SCROLLBAR}
            >
                <box paddingX={1} paddingTop={1}>
                    <Banner />
                </box>
                {messages.map((msg) =>
                    msg.role === "user" ? (
                        msg.variant === "subagent" ? (
                            <SubagentNotice key={msg.id} message={msg} />
                        ) : (
                            <UserMessage key={msg.id} message={msg} />
                        )
                    ) : (
                        <AssistantMessage key={msg.id} message={msg} />
                    ),
                )}
                <CompactionBanner />
            </scrollbox>
            {/* One row that is both the breathing room above the composer and the
                way back down; it never changes height, so the transcript does not
                jump when it appears. */}
            <box
                height={1}
                flexDirection="row"
                justifyContent="flex-end"
                paddingX={1}
                flexShrink={0}
            >
                {atBottom ? null : (
                    <box onMouseUp={jumpToLatest}>
                        <text fg={theme.primary.muted} content="Jump to latest ↓" />
                    </box>
                )}
            </box>
        </box>
    );
}
