/** Root-level suggestion menu: drawn above everything, over the transcript.
 *
 *  Positioned by absolute coordinates measured from the composer box
 *  (`anchorY`), the way opencode's autocomplete does it: an explicit `top`,
 *  `left`, `width` and `height`, never an auto-sized absolute box — the frame
 *  and its rows are laid out from different passes otherwise.
 *
 *  The list itself is a scrollbox, again like opencode: the selection can walk
 *  past the visible rows, so the box has to scroll with it instead of slicing a
 *  window (a sliced window hides candidates that are still selectable).
 *
 *  A fill is not decoration: without it the transcript and the launch logo show
 *  through the menu's rows.
 */
import type { ScrollBoxRenderable } from "@opentui/core";
import { useTerminalDimensions } from "@opentui/react";
import { useEffect, useRef } from "react";
import { useTheme } from "../context/theme.tsx";
import { useMenuStore } from "../stores/menu-store.ts";

/** Border rows only: the list is padded horizontally, never vertically, so the
 *  panel hugs its rows instead of floating them in an empty band. */
export const MENU_CHROME = 2;
/** Rows the menu shows at once; the rest scroll. */
export const MENU_ROWS = 6;

export function MenuOverlay({
    anchorY,
    anchorX,
    anchorWidth,
    anchorEdgeY,
}: {
    anchorY: number;
    anchorX: number;
    anchorWidth: number;
    /** Row the menu's bottom edge touches; defaults to the composer's top. */
    anchorEdgeY?: number;
}) {
    const theme = useTheme();
    const dimensions = useTerminalDimensions();
    const items = useMenuStore((state) => state.items);
    const selectedIndex = useMenuStore((state) => state.selectedIndex);
    const height = useMenuStore((state) => state.height);
    const listRef = useRef<ScrollBoxRenderable>(null);
    const hover = useMenuStore((state) => state.hover);
    const pick = useMenuStore((state) => state.pick);

    const visible = items.length > 0 && height > 0;
    // Flush with the composer, and never off the top of the screen.
    // The menu is the last child of the root, so its insets are screen
    // coordinates: no conversion, no z-index.
    const edge = anchorEdgeY ?? anchorY;
    const top = Math.max(
        0,
        Math.min(edge - height, dimensions.height - height),
    );
    const rows = Math.max(1, Math.min(MENU_ROWS, items.length));

    // Keep the cursor row in view. The scrollbox owns the offset, so it is read
    // back rather than tracked: a wheel or a drag can move it independently.
    //
    // Retried for a few frames: on the render that opens the menu the scrollbox
    // has not measured its content yet, and a scrollTop set before that is
    // discarded (the same shape as the transcript's jump-to-latest).
    useEffect(() => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        let attempts = 0;
        const reveal = (): void => {
            const box = listRef.current;
            if (!box) return;
            if (items.length > rows && box.scrollHeight <= box.height) {
                if (attempts++ < 20) {
                    timer = setTimeout(reveal, 16);
                }
                return;
            }
            const offset = box.scrollTop;
            if (selectedIndex < offset) {
                box.scrollTop = selectedIndex;
            } else if (selectedIndex >= offset + rows) {
                box.scrollTop = selectedIndex - rows + 1;
            }
        };
        reveal();
        return () => {
            if (timer) clearTimeout(timer);
        };
    }, [selectedIndex, rows, items]);

    return (
        <box
            visible={visible}
            position="absolute"
            top={top}
            left={anchorX}
            // A zero width means the composer has not been measured yet; the
            // poll corrects it a tick later, and 100% keeps the menu visible
            // until then.
            width={anchorWidth > 0 ? anchorWidth : "100%"}
            height={height}
            // Above the transcript, which paints in its own layer; without this
            // the menu's frame lands but its rows are overdrawn. It says nothing
            // about the composer: the menu never overlaps it (seam is 0).
            zIndex={100}
            flexDirection="column"
            paddingX={1}
            border
            borderStyle="single"
            borderColor={theme.border.base}
            backgroundColor={theme.background.raised}
        >
            <scrollbox
                ref={listRef}
                height={rows}
                scrollY
                // The composer keeps the keyboard; the wheel only moves the list.
                focusable={false}
                scrollbarOptions={{ visible: false }}
            >
                {items.map((item, index) => {
                    const selected = index === selectedIndex;
                    return (
                        // A row is one clickable line: hovering moves the
                        // selection (so the keyboard continues from there) and a
                        // click accepts it, exactly like Enter.
                        <box
                            key={item.id}
                            flexDirection="row"
                            height={1}
                            onMouseOver={() => hover(index)}
                            onMouseUp={() => pick(index)}
                        >
                            <text
                                height={1}
                                fg={selected ? theme.primary.base : theme.text.faint}
                                content={`${selected ? "▸ " : "  "}${item.usage}  ${item.description}`}
                            />
                        </box>
                    );
                })}
            </scrollbox>
        </box>
    );
}
