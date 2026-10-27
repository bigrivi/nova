/** Launch screen decoration: the block-letter mark shown above the composer. */
import { memo } from "react";
import { NovaLogo } from "./NovaLogo.tsx";

export const LaunchScreen = memo(function LaunchScreen() {
    return (
        <box alignItems="center" marginBottom={2}>
            <NovaLogo />
        </box>
    );
});
