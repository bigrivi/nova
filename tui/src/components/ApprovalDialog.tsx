/** Command/tool approval dialog: shows the pending action, approve/reject */
import { useKeyboard } from "@opentui/react";
import { approveCommand } from "../api/nova-api.ts";
import { approvalCopy } from "../lib/approval-copy.ts";
import {
    type ApprovalPending,
    useApprovalStore,
} from "../stores/approval-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { useTheme } from "../context/theme.tsx";

export function ApprovalDialog({ pending }: { pending: ApprovalPending }) {
    const theme = useTheme();
    const { title, block, scope } = approvalCopy(pending);
    const color = pending.dangerous ? theme.feedback.error : theme.feedback.running;

    /** Clear the visible prompt, keeping the tab badge only if another request
     *  for the same session was promoted behind it. */
    function clearPrompt(): void {
        useApprovalStore.getState().setPending(null);
        const head = useApprovalStore.getState().pending;
        const tab = useTabStore
            .getState()
            .tabs.find((item) => item.sessionId === pending.sessionId);
        if (tab) {
            useTabStore
                .getState()
                .setAttention(
                    tab.id,
                    head?.sessionId === pending.sessionId ? "approval" : null,
                );
        }
    }

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
        clearPrompt();
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
        clearPrompt();
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
            backgroundColor={theme.background.base}
        >
            <text fg={color}>{title}</text>
            {pending.description &&
            pending.description !== pending.command ? (
                <text fg={theme.text.faint} content={pending.description} />
            ) : null}
            {block ? <text fg={theme.text.base} content={block} /> : null}
            {scope ? <text fg={theme.text.muted} content={scope} /> : null}
            <box flexDirection="row" gap={2}>
                <text fg={theme.text.muted} content="[y] Approve" />
                {pending.rememberable ? (
                    <text fg={theme.text.muted} content="[a] Approve & Remember" />
                ) : null}
                <text fg={theme.text.muted} content="[n] Reject" />
            </box>
        </box>
    );
}
