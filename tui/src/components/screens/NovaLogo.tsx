/** Block-letter NOVA mark shown above the launch composer.
 *
 *  Four 5x4 glyphs in the accent-text hue, bold, with a tinted backdrop
 *  behind each block cell for a soft shadow. Collapses responsively:
 *  hidden on short terminals, single-line wordmark on narrow ones.
 */
import { TextAttributes } from "@opentui/core";
import { useTerminalDimensions } from "@opentui/react";
import { useTheme } from "../../context/theme.tsx";
import { mixColor } from "../../themes/dim.ts";

/** Below this terminal height the mark is dropped to save room. */
export const LOGO_MIN_HEIGHT = 14;
/** Below this terminal width the full mark gives way to one line. */
export const LOGO_COMPACT_WIDTH = 56;

const N = ["█   █", "██  █", "█ █ █", "█  ██"];
const O = [" ███ ", "█   █", "█   █", " ███ "];
const V = ["█   █", "█   █", " █ █ ", "  █  "];
const A = [" ███ ", "█   █", "█████", "█   █"];

/** Full mark rows, letters joined with a two-column gap (26 wide). */
export const LOGO_ROWS: readonly string[] = N.map((_, row) =>
    [N, O, V, A].map((letter) => letter[row]).join("  "),
);

/** Single-line fallback for narrow terminals. */
export const LOGO_COMPACT = "N O V A";

export function NovaLogo() {
    const theme = useTheme();
    const dims = useTerminalDimensions();
    if (dims.height < LOGO_MIN_HEIGHT) return null;

    const fg = theme.accentText;
    const shadow = mixColor(theme.background, fg, 0.25);
    const bold = TextAttributes.BOLD;

    if (dims.width < LOGO_COMPACT_WIDTH) {
        return (
            <text
                fg={fg}
                attributes={bold}
                selectable={false}
                content={LOGO_COMPACT}
            />
        );
    }
    return (
        <box flexDirection="column">
            {LOGO_ROWS.map((line) => (
                <box key={line} flexDirection="row">
                    {Array.from(line).map((char, index) =>
                        char === " " ? (
                            <text key={index} selectable={false}>
                                {" "}
                            </text>
                        ) : (
                            <text
                                key={index}
                                fg={fg}
                                bg={shadow}
                                attributes={bold}
                                selectable={false}
                            >
                                {char}
                            </text>
                        ),
                    )}
                </box>
            ))}
        </box>
    );
}
