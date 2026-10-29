/** Read-only view of the mode and rules a tool call is judged by.
 *
 *  Nothing here writes: the mode is changed with Shift+Tab (per turn) and the
 *  rules only by editing the file shown at the top.
 */
import { useKeyboard } from "@opentui/react";
import { usePermissionStore } from "../../stores/permission-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { policyLines } from "../../lib/permissions-format.ts";
import { ScreenPanel } from "./ScreenPanel.tsx";

export function PermissionsScreen() {
    const theme = useTheme();
    const mode = usePermissionStore((state) => state.mode);
    const policy = usePermissionStore((state) => state.policy);
    const lines = policyLines(policy, mode);

    useKeyboard((key) => {
        if (key.name === "escape" || key.name === "q") {
            useScreenStore.getState().close();
        }
    });

    return (
        <ScreenPanel width="70%">
            <box flexDirection="column" gap={1}>
                <text fg={theme.text.base} content="Permissions" />
                <box flexDirection="column">
                    {lines.map((line) => (
                        <text
                            key={line}
                            fg={theme.text.muted}
                            content={line}
                        />
                    ))}
                </box>
                <text
                    fg={theme.text.faint}
                    content="shift+tab cycles the mode · esc closes"
                />
            </box>
        </ScreenPanel>
    );
}
