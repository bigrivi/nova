/** Root component: layout orchestration and modal layer.
 *  Command dispatch lives in ../commands/dispatch.ts, screen rendering in
 *  ./screens/ScreenHost.tsx, keybindings in ../hooks/useGlobalKeys.ts, and
 *  the startup requests in ../hooks/. */
import { useTerminalDimensions } from "@opentui/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { selectIsLaunching, useChatStore } from "../stores/chat-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { ThemeOverride, useTheme } from "../context/theme.tsx";
import { dimTheme } from "../themes/fx/dim.ts";
import type { ComposerCommandHandler } from "./Composer.tsx";
import { MessageList } from "./MessageList.tsx";
import { buildHints, HINT_MS, motionEnabled } from "./screens/launch.ts";
import { ScreenHost } from "./screens/ScreenHost.tsx";
import { MenuOverlay } from "./MenuOverlay.tsx";
import { useMenuStore } from "../stores/menu-store.ts";
import { useSidebarStore } from "../stores/sidebar-store.ts";
import { StatusBar } from "./StatusBar.tsx";
import { Toast } from "./Toast.tsx";
import { SessionTabBar } from "./SessionTabBar.tsx";
import { BottomDock } from "./BottomDock.tsx";
import { Sidebar } from "./sidebar/Sidebar.tsx";
import { SIDEBAR_DOCK_MIN_WIDTH } from "./sidebar/layout.ts";
import { dispatchCommand } from "../commands/dispatch.ts";
import { useAppBootstrap } from "../hooks/useAppBootstrap.ts";
import { useGlobalKeys } from "../hooks/useGlobalKeys.ts";
import { useSessionBootstrap } from "../hooks/useSessionBootstrap.ts";
import { focusSession, selectTab } from "../lib/tab-actions.ts";

export type ExitHandler = () => void;

/** Motion is a property of the environment, not of the render. */
const ANIMATE = motionEnabled(process.env);

export function App({ onExit }: { onExit: ExitHandler }) {
    const askQuestions = useAskUserStore((state) => state.active);
    const askTabId = useAskUserStore((state) => state.activeTabId);
    const approvalSessionId = useApprovalStore(
        (state) => state.pending?.sessionId ?? null,
    );
    const approvalRequestId = useApprovalStore(
        (state) => state.pending?.requestId ?? null,
    );
    // Derived booleans, not the values behind them: the transcript changes on
    // every token, and a subscription to it would re-render the whole shell.
    // A null session means nothing has been loaded yet; `loadHistory` sets both
    // fields at once, so picking a session never flashes the launch screen.
    const launching = useChatStore(selectIsLaunching);
    const hasScreen = useScreenStore((state) => state.current !== null);
    const [hintIndex, setHintIndex] = useState(0);
    const [savedSessions, setSavedSessions] = useState(0);
    const menuAnchor = useMenuStore((state) => state.anchor);
    const sidebarOpen = useSidebarStore((state) => state.open);
    const dimensions = useTerminalDimensions();
    // Docked beside the transcript when both fit; otherwise the panel takes the
    // screen (see Sidebar).
    const docked = dimensions.width >= SIDEBAR_DOCK_MIN_WIDTH;

    // Open on a wide terminal by default, like opencode's session.sidebar: auto.
    // Only once, on mount: a manual toggle later wins over a resize.
    const initializedRef = useRef(false);
    useEffect(() => {
        if (initializedRef.current) return;
        if (dimensions.width === 0) return;
        initializedRef.current = true;
        if (docked) {
            useSidebarStore.getState().setOpen(true);
        }
    }, [dimensions.width, docked]);
    const hints = useMemo(() => buildHints(savedSessions), [savedSessions]);
    const theme = useTheme();
    const animate = ANIMATE;

    useEffect(() => {
        if (!launching || !animate) return;
        const timer = setInterval(() => {
            setHintIndex((value) => value + 1);
        }, HINT_MS);
        return () => {
            clearInterval(timer);
        };
    }, [launching, animate]);

    // Offering the resume hint needs the count, not the sessions themselves.
    // The same fetch drops restored tabs whose session is gone and refreshes
    // their titles from the backend.
    useSessionBootstrap(setSavedSessions);
    useAppBootstrap();

    // A translucent scrim eats double-width glyphs, so the transcript is dimmed
    // by recolouring its palette instead of drawing over it.
    const quiet = useMemo(
        () => (hasScreen ? dimTheme(theme) : null),
        [hasScreen, theme],
    );

    // A background approval or question owns the modal: bring its tab forward so
    // the dialog and the transcript it refers to cannot disagree.
    useEffect(() => {
        if (approvalSessionId) {
            focusSession(approvalSessionId);
        }
    }, [approvalRequestId, approvalSessionId]);

    useEffect(() => {
        if (askQuestions && askTabId) {
            selectTab(askTabId);
        }
    }, [askQuestions, askTabId]);

    useGlobalKeys({ onExit });

    const handleCommand: ComposerCommandHandler = (id, args) =>
        dispatchCommand(id, args, { onExit });

    return (
        <box
            width="100%"
            height="100%"
            flexDirection="column"
            flexGrow={1}
            padding={0}
            gap={0}
            marginBottom={1}
            backgroundColor={theme.background.base}
        >
            <box flexDirection="row" flexGrow={1} flexShrink={1} minHeight={0}>
                <box
                    flexDirection="column"
                    flexGrow={1}
                    flexShrink={1}
                    minWidth={0}
                    minHeight={0}
                >
                    <ThemeOverride value={quiet}>
                        <box
                            flexDirection="column"
                            flexGrow={1}
                            flexShrink={1}
                            minHeight={0}
                        >
                            <SessionTabBar />
                            {launching ? null : <MessageList />}
                            <BottomDock
                                launching={launching}
                                hintIndex={hintIndex}
                                hints={hints}
                                animate={animate}
                                onCommand={handleCommand}
                            />
                        </box>
                        <StatusBar />
                    </ThemeOverride>
                </box>
                {sidebarOpen && docked ? (
                    <Sidebar presentation="docked" />
                ) : null}
            </box>
            {/* Narrow terminal: the panel takes the screen instead of squeezing
                the transcript. It is painted over the shell, which stays mounted
                so a draft in the composer survives opening and closing it. */}
            {sidebarOpen && !docked ? (
                <Sidebar presentation="fullscreen" />
            ) : null}
            <ScreenHost />
            <MenuOverlay
                anchorY={menuAnchor.y}
                anchorX={menuAnchor.x}
                anchorWidth={menuAnchor.width}
                anchorEdgeY={menuAnchor.edgeY}
            />
            <Toast />
        </box>
    );
}
