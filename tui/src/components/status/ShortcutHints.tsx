/** Keyboard hints: keys in a dimmer tone, labels slightly brighter. */
import { useTheme } from "../../context/theme.tsx";
import type { Shortcut } from "../../lib/status-format.ts";

export function ShortcutHints({
    shortcuts,
}: {
    shortcuts: readonly Shortcut[];
}) {
    const theme = useTheme();
    return (
        <box flexDirection="row" alignItems="center" flexShrink={0} gap={2}>
            {shortcuts.map((item) => (
                <box
                    key={item.key}
                    flexDirection="row"
                    alignItems="center"
                    gap={1}
                >
                    <text fg={theme.text.faint} content={item.key} />
                    <text fg={theme.text.muted} content={item.label} />
                </box>
            ))}
        </box>
    );
}
