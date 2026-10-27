/** Launch screen: an empty session shows only a floating composer, centred both
 *  ways, with a slowly breathing border and a rotating hint. */
import { useEffect, useState } from "react";
import { useTheme } from "../../context/theme.tsx";
import { mixColor } from "../../themes/dim.ts";
import { Composer, type ComposerCommandHandler } from "../Composer.tsx";
import { breath, placeholderAt, TICK_MS } from "./launch.ts";
import { NovaLogo } from "./NovaLogo.tsx";

const HINTS = [
    "Ask anything, or type / for commands",
    "Describe what you want to change...",
    "Paste an error, I'll track it down...",
];

export function LaunchScreen({
    onCommand,
}: {
    onCommand: ComposerCommandHandler;
}) {
    const theme = useTheme();
    const [tick, setTick] = useState(0);

    useEffect(() => {
        const timer = setInterval(() => {
            setTick((value) => value + 1);
        }, TICK_MS);
        return () => {
            clearInterval(timer);
        };
    }, []);

    const borderColor = mixColor(theme.border, theme.accent, breath(tick) * 0.7);

    return (
        <box flexGrow={1} justifyContent="center" alignItems="center">
            <box width="60%" maxWidth={76} flexDirection="column">
                <box alignItems="center" marginBottom={2}>
                    <NovaLogo />
                </box>
                <box width="100%">
                    <Composer
                        onCommand={onCommand}
                        variant="card"
                        borderColor={borderColor}
                        placeholder={placeholderAt(tick, HINTS)}
                    />
                </box>
            </box>
        </box>
    );
}
