/** Root-level suggestion menu: drawn above everything, over the transcript.
 *
 *  Positioned by absolute coordinates measured from the composer box
 *  (`anchorY`), the way opencode's autocomplete does it: an explicit `top`,
 *  `left`, `width` and `height`, never an auto-sized absolute box — the frame
 *  and its rows are laid out from different passes otherwise.
 *
 *  A fill is not decoration: without it the transcript and the launch logo show
 *  through the menu's rows.
 */
import { useTerminalDimensions } from "@opentui/react";
import { useTheme } from "../context/theme.tsx";
import { windowAround } from "../lib/suggestion-window.ts";
import { useMenuStore } from "../stores/menu-store.ts";

/** Border (2) plus vertical padding (2). */
export const MENU_CHROME = 4;
/** Rows the menu shows at once. */
export const MENU_ROWS = 6;

export function MenuOverlay({
    anchorY,
    anchorX,
    anchorWidth,
}: {
    anchorY: number;
    anchorX: number;
    anchorWidth: number;
}) {
    const theme = useTheme();
    const dimensions = useTerminalDimensions();
    const items = useMenuStore((state) => state.items);
    const selectedIndex = useMenuStore((state) => state.selectedIndex);
    const height = useMenuStore((state) => state.height);

    const visible = items.length > 0 && height > 0;
    // One row of clearance, and never off the top of the screen.
    const top = Math.max(
        0,
        Math.min(anchorY - height - 1, dimensions.height - height),
    );
    const { start, hiddenAbove, hiddenBelow } = windowAround(
        selectedIndex,
        items.length,
        MENU_ROWS,
    );

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
            zIndex={100}
            flexDirection="column"
            paddingX={1}
            paddingY={1}
            border
            borderStyle="single"
            borderColor={theme.border.base}
            backgroundColor={theme.background.raised}
        >
            {hiddenAbove > 0 ? (
                <text
                    height={1}
                    fg={theme.text.faint}
                    content={`  ↑ ${hiddenAbove} more`}
                />
            ) : null}
            {items.slice(start, start + MENU_ROWS).map((item, offset) => {
                const index = start + offset;
                const selected = index === selectedIndex;
                return (
                    <text
                        key={item.id}
                        height={1}
                        fg={selected ? theme.primary.base : theme.text.faint}
                        content={`${selected ? "▸ " : "  "}${item.usage}  ${item.description}`}
                    />
                );
            })}
            {hiddenBelow > 0 ? (
                <text
                    height={1}
                    fg={theme.text.faint}
                    content={`  ↓ ${hiddenBelow} more`}
                />
            ) : null}
        </box>
    );
}
