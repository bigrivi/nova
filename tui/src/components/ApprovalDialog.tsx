/** Command/tool approval dialog: shows the pending action, approve/reject */
import { useKeyboard } from "@opentui/react";
import { approveCommand } from "../api/nova-api.ts";
import { approvalCopy } from "../lib/approval-copy.ts";
import {
    type ApprovalPending,
    useApprovalStore,
} from "../stores/approval-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { theme } from "../theme.ts";

export function ApprovalDialog({ pending }: { pending: ApprovalPending }) {
    const { title, block, scope } = approvalCopy(pending);
    const color = pending.dangerous ? theme.error : theme.running;

    useKeyboard((key) => {
        if (key.name === "y" || key.name === "return" || key.name === "enter") {
            void resolve(false);
            return;
        }
        if (key.name === "a" && pending.rememberable) {
            void resolve(true);
            return;
        }
        if (key.name === "n" || key.name === "escape") {
            void reject();
        }
    });

    async function resolve(remember: boolean): Promise<void> {
        useApprovalStore.getState().setPending(null);
        try {
            await approveCommand({
                sessionId: pending.sessionId,
                requestId: pending.requestId,
                approved: true,
                remember,
            });
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

    async function reject(): Promise<void> {
        useApprovalStore.getState().setPending(null);
        try {
            await approveCommand({
                sessionId: pending.sessionId,
                requestId: pending.requestId,
                approved: false,
            });
        } catch (err) {
            useToastStore
                .getState()
                .show(
                    `Reject failed: ${err instanceof Error ? err.message : String(err)}`,
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
            borderColor={color}
            backgroundColor={theme.surfaceDeep}
        >
            <text fg={color}>{title}</text>
            {pending.description &&
            pending.description !== pending.command ? (
                <text fg={theme.subtle} content={pending.description} />
            ) : null}
            {block ? <text fg={theme.foreground} content={block} /> : null}
            {scope ? <text fg={theme.muted} content={scope} /> : null}
            <box flexDirection="row" gap={2}>
                <text fg={theme.muted} content="[y] Approve" />
                {pending.rememberable ? (
                    <text fg={theme.muted} content="[a] Approve & Remember" />
                ) : null}
                <text fg={theme.muted} content="[n] Reject" />
            </box>
        </box>
    );
}
