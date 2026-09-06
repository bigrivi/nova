/** Command approval dialog: shows the pending command, approve/reject */
import { useKeyboard } from "@opentui/react";
import { approveCommand } from "../api/nova-api.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { theme } from "../theme.ts";

export function ApprovalDialog({
    sessionId,
    requestId,
    command,
    description,
}: {
    sessionId: string;
    requestId: string;
    command: string;
    description: string;
}) {
    useKeyboard((key) => {
        if (key.name === "y" || key.name === "return" || key.name === "enter") {
            resolve(true);
            return;
        }
        if (key.name === "n" || key.name === "escape") {
            resolve(false);
        }
    });

    async function resolve(approved: boolean): Promise<void> {
        useApprovalStore.getState().setPending(null);
        try {
            await approveCommand({ sessionId, requestId, approved });
        } catch (err) {
            // Surface backend rejections (unknown session/request, session
            // busy) instead of failing silently; the turn stays parked and
            // the user can retry once the conflicting request finishes.
            useToastStore
                .getState()
                .show(
                    `Approve failed: ${err instanceof Error ? err.message : String(err)}`,
                    4000,
                );
        }
    }

    return (
        <box
            flexDirection="column"
            flexShrink={0}
            paddingX={2}
            paddingY={1}
            gap={0}
            border={["top", "bottom"]}
            borderStyle="single"
            borderColor="#d29922"
            backgroundColor={theme.surfaceDeep}
        >
            <text fg={theme.running}>Command approval required</text>
            {description ? <text fg={theme.subtle} content={description} /> : null}
            <text fg={theme.running} content={command} />
            <text fg={theme.muted}>[y] Approve [n] Reject</text>
        </box>
    );
}
