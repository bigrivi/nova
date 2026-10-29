/** A scrollable block of text in the standard modal panel.
 *
 *  Shared by the diff and review screens: both show output the user reads and
 *  scrolls, neither edits it, and duplicating the scrollbox plumbing twice is
 *  how the two would drift apart.
 */
import type { ScrollBoxRenderable } from "@opentui/core";
import { useKeyboard, useTerminalDimensions } from "@opentui/react";
import { useRef } from "react";
import { useTheme } from "../../context/theme.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";

/** Rows the panel spends before the text: padding, header, footer. */
const CHROME_ROWS = 14;

export function ScrollText({
    title,
    subtitle,
    lines,
    tone,
    footer,
    onClose,
}: {
    title: string;
    subtitle?: string;
    lines: string[];
    /** Colour for one line; omitted means the body colour. */
    tone?: (line: string) => string;
    footer?: string;
    onClose: () => void;
}) {
    const theme = useTheme();
    const dimensions = useTerminalDimensions();
    const scrollRef = useRef<ScrollBoxRenderable>(null);

    useKeyboard((key) => {
        if (key.name === "escape" || key.name === "q") {
            onClose();
            return;
        }
        const box = scrollRef.current;
        if (!box) return;
        const page = Math.max(1, box.height - 1);
        if (key.name === "down" || key.name === "j") box.scrollTop += 1;
        if (key.name === "up" || key.name === "k") box.scrollTop -= 1;
        if (key.name === "pagedown") box.scrollTop += page;
        if (key.name === "pageup") box.scrollTop -= page;
    });

    return (
        <ScreenPanel width="95%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.text.base} content={title} />
                {subtitle ? (
                    <text fg={theme.text.muted} content={subtitle} />
                ) : null}
                <scrollbox
                    ref={scrollRef}
                    height={Math.max(3, dimensions.height - CHROME_ROWS)}
                    scrollY
                    focusable={false}
                    scrollbarOptions={{ visible: true }}
                >
                    {lines.map((line, index) => (
                        <text
                            key={`${index}-${line.slice(0, 8)}`}
                            height={1}
                            fg={tone ? tone(line) : theme.text.base}
                            content={line || " "}
                        />
                    ))}
                </scrollbox>
                <text
                    fg={theme.text.faint}
                    content={footer ?? "↑↓ scroll · esc close"}
                />
            </box>
        </ScreenPanel>
    );
}
