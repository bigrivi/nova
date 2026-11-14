/** Session panel: what the current session is doing, and what it has spent.
 *
 *  Modelled on opencode's panel: one component, two presentations, and the
 *  terminal width decides which. Docked it takes a fixed column beside the
 *  transcript; too narrow for both, it covers the screen instead of squeezing
 *  the transcript into something unreadable.
 *
 *  Each section is its own component and reads its own store, so a panel that
 *  has nothing to say returns null and costs nothing.
 */
import { TextAttributes } from "@opentui/core";
import { homedir } from "node:os";

import { useApp } from "../../context/app.tsx";
import { useTheme } from "../../context/theme.tsx";
import { shortenPath } from "../../lib/status-format.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useTabStore } from "../../stores/tab-store.ts";
import { WORKSPACE_DIR } from "../../workspace.ts";
import { CompactingPanel } from "./CompactingPanel.tsx";
import { ContextPanel } from "./ContextPanel.tsx";
import { McpPanel } from "./McpPanel.tsx";
import { SIDEBAR_WIDTH } from "./layout.ts";
import { TodoPanel } from "./TodoPanel.tsx";

export type SidebarPresentation = "docked" | "fullscreen";

function SidebarHeader() {
    const theme = useTheme();
    const sessionId = useChatStore((state) => state.sessionId);
    const agentName = useChatStore((state) => state.agentName);
    const tabs = useTabStore((state) => state.tabs);
    const title =
        tabs.find((tab) => tab.sessionId === sessionId)?.title ?? "New session";

    return (
        <box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
            <text
                fg={theme.text.base}
                attributes={TextAttributes.BOLD}
                content={title}
                wrapMode="none"
            />
            <text
                fg={theme.text.muted}
                content={agentName}
                wrapMode="none"
            />
        </box>
    );
}

function SidebarFooter() {
    const theme = useTheme();
    const app = useApp();
    const path = shortenPath(WORKSPACE_DIR, homedir(), SIDEBAR_WIDTH - 2);

    return (
        <box flexDirection="column" flexShrink={0} paddingX={1} paddingY={1}>
            <text fg={theme.text.muted} content={path} wrapMode="none" />
            {app.branch ? (
                <text
                    fg={theme.text.faint}
                    content={`⎇ ${app.branch}`}
                    wrapMode="none"
                />
            ) : null}
        </box>
    );
}

export function Sidebar({
    presentation,
}: {
    presentation: SidebarPresentation;
}) {
    const theme = useTheme();
    const fullscreen = presentation === "fullscreen";

    return (
        <box
            flexDirection="column"
            flexShrink={0}
            minHeight={0}
            width={fullscreen ? "100%" : SIDEBAR_WIDTH}
            // A docked panel sits on a raised surface; fullscreen owns the canvas.
            backgroundColor={
                fullscreen ? theme.background.base : theme.background.raised
            }
            border={fullscreen ? undefined : ["left"]}
            borderColor={theme.border.base}
            {...(fullscreen
                ? {
                      position: "absolute" as const,
                      left: 0,
                      right: 0,
                      top: 0,
                      bottom: 0,
                  }
                : {})}
        >
            <SidebarHeader />
            <scrollbox flexGrow={1} minHeight={0} scrollY>
                <box flexDirection="column" gap={1} paddingX={1} paddingBottom={1}>
                    <ContextPanel />
                    <TodoPanel />
                    <CompactingPanel />
                    <McpPanel />
                </box>
            </scrollbox>
            <SidebarFooter />
        </box>
    );
}
