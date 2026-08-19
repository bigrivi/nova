/** Command approval dialog: shows the pending command, approve/reject */
import { useKeyboard } from "@opentui/react";
import { approveCommand } from "../api/nova-api.ts";
import { useApprovalStore } from "../stores/approval-store.ts";

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
        if (key.name === "y" || key.name === "enter") {
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
        } catch {
            // A failed approval does not block the UI; the stream will end with an error
        }
    }

    return (
        <box
            position="absolute"
            left="20%"
            right="20%"
            top="25%"
            paddingX={2}
            paddingY={2}
            border
            borderStyle="rounded"
            borderColor="#d29922"
            backgroundColor="#0d1117"
        >
            <text fg="#d29922">Command approval required</text>
            {description ? <text fg="#8b949e" content={description} /> : null}
            <text fg="#e3b341" content={command} />
            <text fg="#6e7681">[y] Approve [n] Reject</text>
        </box>
    );
}
