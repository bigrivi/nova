/** Horizontal session-tab strip: state, hover close, and hover marquee.
 *
 *  Visual standard follows opencode's HorizontalSessionTabs: a fixed
 *  status cell (lead, glyph, gap) so titles never move, a close glyph that
 *  appears on hover, a `+` for a new draft, and `‹N` / `N›` overflow markers.
 */
import { useEffect, useRef, useState } from "react";
import { useTerminalDimensions } from "@opentui/react";
import { useTheme } from "../context/theme.tsx";
import { mixColor } from "../themes/color.ts";
import { truncateEnd } from "../lib/display-width.ts";
import {
    MARQUEE_DELAY_MS,
    MARQUEE_TICK_MS,
    marqueeCycleWidth,
    marqueeFrame,
    marqueeOverflows,
} from "../lib/marquee.ts";
import {
    adaptiveTabLayout,
    TAB_ADD_WIDTH,
    TAB_STATUS_WIDTH,
    tabOverflowWidth,
} from "../lib/tab-layout.ts";
import { motionEnabled } from "./screens/launch.ts";
import { closeTab, openDraftTab, selectTab } from "../lib/tab-actions.ts";
import { useTabStreaming } from "../stores/chat-store.ts";
import { useTabStore, type SessionTab } from "../stores/tab-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { Spinner } from "./tool-block/Spinner.tsx";

/** One hover marquee at a time: only the hovered tab starts these timers. */
function useMarquee(hovered: boolean, title: string, width: number): number {
    const [offset, setOffset] = useState(0);
    const animate = motionEnabled(process.env);

    useEffect(() => {
        setOffset(0);
        if (
            !hovered ||
            !animate ||
            width <= 4 ||
            !marqueeOverflows(title, width)
        ) {
            return;
        }
        const cycle = marqueeCycleWidth(title);
        let interval: ReturnType<typeof setInterval> | null = null;
        const stop = () => {
            if (interval !== null) {
                clearInterval(interval);
                interval = null;
            }
        };
        const delay = setTimeout(() => {
            setOffset(1);
            interval = setInterval(() => {
                setOffset((value) => {
                    if (value + 1 < cycle) {
                        return value + 1;
                    }
                    stop();
                    return 0;
                });
            }, MARQUEE_TICK_MS);
            interval.unref?.();
        }, MARQUEE_DELAY_MS);
        delay.unref?.();
        return () => {
            clearTimeout(delay);
            stop();
        };
    }, [hovered, title, width, animate]);

    return offset;
}

function useHoverDelay(): {
    hovered: boolean;
    enter: () => void;
    leave: () => void;
} {
    const [hovered, setHovered] = useState(false);
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(
        () => () => {
            if (timer.current !== null) {
                clearTimeout(timer.current);
                timer.current = null;
            }
        },
        [],
    );

    return {
        hovered,
        enter: () => {
            if (timer.current !== null) {
                clearTimeout(timer.current);
                timer.current = null;
            }
            setHovered(true);
        },
        // Moving from the title onto the absolutely positioned close cell fires
        // the parent's mouse-out first; defer the clear by one tick so the close
        // glyph does not vanish under the pointer.
        leave: () => {
            if (timer.current !== null) {
                clearTimeout(timer.current);
            }
            timer.current = setTimeout(() => {
                timer.current = null;
                setHovered(false);
            }, 0);
            timer.current.unref?.();
        },
    };
}

function tabBackground(
    theme: ReturnType<typeof useTheme>,
    tab: SessionTab,
    selected: boolean,
    hovered: boolean,
): string | undefined {
    if (selected) {
        return mixColor(theme.background.base, theme.primary.base, 0.22);
    }
    if (hovered) {
        return theme.background.raised;
    }
    if (tab.unread === "error") {
        return mixColor(theme.background.base, theme.feedback.error, 0.12);
    }
    if (tab.unread === "activity") {
        return mixColor(theme.background.base, theme.primary.base, 0.12);
    }
    if (tab.attention) {
        return mixColor(theme.background.base, theme.feedback.running, 0.12);
    }
    return undefined;
}

function TabItem({
    tab,
    width,
    interactive,
}: {
    tab: SessionTab;
    width: number;
    interactive: boolean;
}) {
    const theme = useTheme();
    const selected = useTabStore((state) => state.activeId === tab.id);
    const busy = useTabStreaming(tab.id);
    const attention = tab.attention;
    const unread = tab.unread;
    const { hovered, enter, leave } = useHoverDelay();
    const [closeHovered, setCloseHovered] = useState(false);

    const restingTitleWidth = Math.max(1, width - TAB_STATUS_WIDTH - 1);
    const titleWidth = hovered
        ? Math.max(1, restingTitleWidth - 2)
        : restingTitleWidth;
    const offset = useMarquee(hovered, tab.title, titleWidth);
    const title = hovered
        ? marqueeFrame(tab.title, titleWidth, offset)
        : truncateEnd(tab.title, titleWidth);

    let marker: string | null = null;
    let markerColor = theme.text.faint;
    if (attention === "approval") {
        marker = "!";
        markerColor = theme.feedback.running;
    } else if (attention === "question") {
        marker = "?";
        markerColor = theme.feedback.running;
    } else if (unread) {
        marker = "•";
        markerColor =
            unread === "error" ? theme.feedback.error : theme.primary.base;
    }

    const foreground =
        selected || hovered
            ? theme.text.base
            : unread === "error"
              ? theme.feedback.error
              : unread === "activity"
                ? theme.primary.base
                : theme.text.muted;

    return (
        <box
            width={width}
            height={1}
            flexShrink={0}
            position="relative"
            flexDirection="row"
            backgroundColor={tabBackground(theme, tab, selected, hovered)}
            onMouseOver={enter}
            onMouseOut={leave}
            onMouseDown={(event) => {
                if (!interactive) return;
                if (event.button === 1) {
                    event.stopPropagation();
                    closeTab(tab.id);
                }
            }}
            onMouseUp={(event) => {
                if (!interactive) return;
                if (event.button !== 0) return;
                selectTab(tab.id);
            }}
        >
            <box
                width={TAB_STATUS_WIDTH}
                height={1}
                flexShrink={0}
                flexDirection="row"
                justifyContent="flex-end"
                paddingRight={1}
            >
                {busy && !attention ? (
                    <Spinner />
                ) : (
                    <text fg={markerColor} wrapMode="none">
                        {marker}
                    </text>
                )}
            </box>
            <text fg={foreground} wrapMode="none" flexShrink={0}>
                {title}
            </text>
            {hovered ? (
                <text
                    position="absolute"
                    right={1}
                    width={1}
                    zIndex={2}
                    fg={closeHovered ? theme.text.base : theme.text.muted}
                    onMouseOver={() => {
                        setCloseHovered(true);
                        enter();
                    }}
                    onMouseOut={() => setCloseHovered(false)}
                    onMouseUp={(event) => {
                        if (!interactive) return;
                        if (event.button !== 0) return;
                        event.stopPropagation();
                        closeTab(tab.id);
                    }}
                >
                    {"✕"}
                </text>
            ) : null}
        </box>
    );
}

export function SessionTabBar() {
    const theme = useTheme();
    const dimensions = useTerminalDimensions();
    const tabs = useTabStore((state) => state.tabs);
    const activeId = useTabStore((state) => state.activeId);
    const screenOpen = useScreenStore((state) => state.current !== null);
    const [addHovered, setAddHovered] = useState(false);
    const previousStart = useRef(0);

    if (tabs.length === 0) {
        return null;
    }

    const activeTab = tabs.find((tab) => tab.id === activeId);
    // A draft already owns the new-session slot; a second `+` would be noise.
    const showAdd = activeTab?.sessionId !== null;
    const available = Math.max(
        1,
        dimensions.width - (showAdd ? TAB_ADD_WIDTH : 0),
    );
    const layout = adaptiveTabLayout(
        tabs,
        activeId,
        available,
        previousStart.current,
    );
    previousStart.current = layout.start;

    return (
        <box
            height={1}
            flexShrink={0}
            flexDirection="row"
            onMouseOut={() => setAddHovered(false)}
        >
            {layout.before > 0 ? (
                <text
                    width={tabOverflowWidth(layout.before)}
                    fg={theme.text.muted}
                    wrapMode="none"
                >
                    {`‹${layout.before}`}
                </text>
            ) : null}
            {layout.visible.map((tab, index) => (
                <TabItem
                    key={tab.id}
                    tab={tab}
                    width={Math.max(1, layout.widths[index] ?? 1)}
                    interactive={!screenOpen}
                />
            ))}
            {layout.after > 0 ? (
                <text
                    width={tabOverflowWidth(layout.after)}
                    fg={theme.text.muted}
                    wrapMode="none"
                    flexShrink={0}
                >
                    {` ${layout.after}›`}
                </text>
            ) : null}
            {showAdd ? (
                <text
                    width={TAB_ADD_WIDTH}
                    flexShrink={0}
                    fg={addHovered ? theme.text.base : theme.text.muted}
                    onMouseOver={() => setAddHovered(true)}
                    onMouseOut={() => setAddHovered(false)}                    onMouseUp={(event) => {
                        if (screenOpen) return;
                        if (event.button !== 0) return;
                        openDraftTab();
                    }}
                >
                    {" + "}
                </text>
            ) : null}
        </box>
    );
}
