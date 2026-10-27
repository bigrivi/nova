/** Full-screen dim layer behind a screen dialog: keeps the chat visible but out of focus. */
import { RGBA } from "@opentui/core";

// Drawn over whatever is behind it, so the transcript stays readable through
// the scrim instead of disappearing behind an opaque fill.
const DIM = RGBA.fromValues(0, 0, 0, 0.55);

export function ScreenBackdrop() {
    return (
        <box
            position="absolute"
            left={0}
            right={0}
            top={0}
            bottom={0}
            backgroundColor={DIM}
        />
    );
}
