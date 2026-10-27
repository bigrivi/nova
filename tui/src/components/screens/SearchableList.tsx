/** Generic searchable list: filter input + ↑↓ cursor + Enter confirm + Escape close.
 *
 * The scrollbox owns the viewport, so the mouse wheel scrolls natively; the
 * cursor row is scrolled back into view whenever it moves.
 */
import type { InputRenderable, ScrollBoxRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "../../context/theme.tsx";
import { buildRows, rowOf } from "./list-nav.ts";
import { ScreenPanel } from "./ScreenPanel.tsx";

export type SearchableItem = {
    /** Row text, and the default search text. */
    label: string;
    /** Handed to `onSelect` and matched against `defaultValue`. */
    value: string;
    /** Optional group label; a header row is drawn at each group boundary. */
    group?: string;
};

const VIEWPORT_ROWS = 12;
/** Leading gutter every row shares, so group headers line up with labels. */
const MARKER_WIDTH = 3;

// MouseButton is not exported from @opentui/core's root entry.
const LEFT_BUTTON = 0;

function labelMatches(label: string, query: string): boolean {
    return label.toLowerCase().includes(query.toLowerCase());
}

export function SearchableList<T extends SearchableItem>({
    title,
    items,
    filter,
    renderLabel,
    onSelect,
    onClose,
    emptyText = "(empty)",
    defaultValue,
}: {
    title: string;
    items: T[];
    /** Replace the default case-insensitive `label` match. */
    filter?: (item: T, query: string) => boolean;
    /** Row text when `label` alone is not enough (e.g. a trailing timestamp). */
    renderLabel?: (item: T) => string;
    onSelect: (value: string) => void;
    onClose: () => void;
    emptyText?: string;
    /** The item whose value matches this string is marked as current. */
    defaultValue?: string;
}) {
    const theme = useTheme();
    const [query, setQuery] = useState("");
    const [cursor, setCursor] = useState(() =>
        Math.max(
            0,
            items.findIndex((item) => item.value === defaultValue),
        ),
    );
    const inputRef = useRef<InputRenderable>(null);
    const scrollRef = useRef<ScrollBoxRenderable>(null);

    const filtered = useMemo(
        () =>
            items.filter((item) =>
                filter ? filter(item, query) : labelMatches(item.label, query),
            ),
        [items, filter, query],
    );
    const rows = useMemo(
        () => buildRows(filtered, (item) => item.group),
        [filtered],
    );
    const live = useRef({ filtered, cursor });
    live.current = { filtered, cursor };

    useEffect(() => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        let attempts = 0;
        const reveal = () => {
            const box = scrollRef.current;
            if (!box) return;
            // A short list has nothing to scroll, so this is not a pending layout.
            if (
                rows.length > box.height &&
                box.scrollHeight <= box.height &&
                attempts++ < 20
            ) {
                timer = setTimeout(reveal, 16);
                return;
            }
            const row = rowOf(rows, cursor);
            if (row < 0) return;
            const top = box.scrollTop;
            if (row < top) {
                box.scrollTop = row;
            } else if (row >= top + box.height) {
                box.scrollTop = row - box.height + 1;
            }
        };
        reveal();
        return () => {
            if (timer) clearTimeout(timer);
        };
    }, [cursor, filtered]);

    useKeyboard((key) => {
        const { filtered: list, cursor: cur } = live.current;
        if (key.name === "up" || key.name === "down") {
            if (list.length === 0) return;
            const dir = key.name === "up" ? -1 : 1;
            let index = cur + dir;
            if (index < 0) index = 0;
            if (index >= list.length) index = list.length - 1;
            if (index === cur) {
                // At the end of the list: keep scrolling so the group header
                // above the first row can come back into view.
                const box = scrollRef.current;
                if (box) {
                    box.scrollTop = Math.max(
                        0,
                        Math.min(
                            box.scrollTop + dir,
                            box.scrollHeight - box.height,
                        ),
                    );
                }
                return;
            }
            setCursor(index);
            return;
        }
        // Enter is the input's own onSubmit: the renderer runs global handlers
        // first, so selecting here too would submit twice.
        if (key.name === "escape") {
            onClose();
        }
    });

    return (
        <ScreenPanel>
            <text marginLeft={MARKER_WIDTH} fg={theme.accent}>{title}</text>
            <input
                ref={inputRef}
                marginLeft={MARKER_WIDTH}
                flexGrow={1}
                focused
                value={query}
                placeholder="Filter…"
                placeholderColor={theme.muted}
                textColor={theme.foreground}
                focusedTextColor={theme.foreground}
                onInput={(value) => {
                    setQuery(value);
                    setCursor(0);
                }}
                onSubmit={() => {
                    const { filtered: list, cursor: cur } = live.current;
                    const item = list[cur];
                    if (item) {
                        onSelect(item.value);
                    }
                }}
            />
            <scrollbox
                ref={scrollRef}
                height={Math.min(Math.max(rows.length, 1), VIEWPORT_ROWS)}
                scrollY
                focusable={false}
                viewportCulling
                marginTop={1}
                scrollbarOptions={{ visible: false }}
            >
                {rows.map((entry, rowIndex) => {
                    if (entry.kind === "spacer") {
                        return <box key={`s:${rowIndex}`} height={1} />;
                    }
                    if (entry.kind === "header") {
                        return (
                            <text
                                key={`h:${entry.label}`}
                                height={1}
                                fg={theme.accentText}
                                content={`${" ".repeat(MARKER_WIDTH)}${entry.label}`}
                            />
                        );
                    }
                    const isCursor = entry.index === cursor;
                    // Compare values: a filtered-out prefix shifts the indices.
                    const isCurrent = entry.item.value === defaultValue;
                    // On the accent band the row switches to the theme's paired
                    // foreground; the dot follows so it cannot sink into it.
                    const dotFg = isCursor
                        ? theme.accentForeground
                        : theme.accent;
                    const itemFg = isCursor
                        ? theme.accentForeground
                        : theme.foreground;
                    return (
                        <box
                            key={`i:${entry.index}`}
                            flexDirection="row"
                            width="100%"
                            height={1}
                            // Only the cursor row is banded; the current item is
                            // marked by `●` alone, so hovering paints it too.
                            backgroundColor={isCursor ? theme.accent : undefined}
                            onMouseOver={() => setCursor(entry.index)}
                            onMouseUp={(event) => {
                                if (event.button === LEFT_BUTTON) {
                                    onSelect(entry.item.value);
                                }
                            }}
                        >
                            <text
                                width={MARKER_WIDTH}
                                fg={dotFg}
                                content={isCurrent ? " ● " : "   "}
                            />
                            <text
                                fg={itemFg}
                                content={
                                    renderLabel
                                        ? renderLabel(entry.item)
                                        : entry.item.label
                                }
                            />
                        </box>
                    );
                })}
                {filtered.length === 0 ? (
                    <text
                        height={1}
                        fg={theme.foregroundMuted}
                        content={`${" ".repeat(MARKER_WIDTH)}${emptyText}`}
                    />
                ) : null}
            </scrollbox>
            <text marginLeft={MARKER_WIDTH} marginTop={1} fg={theme.muted}>
                {filtered.length > 0
                    ? `↑↓ ${cursor + 1}/${filtered.length} • enter • esc`
                    : "↑↓ • enter • esc"}
            </text>
        </ScreenPanel>
    );
}
