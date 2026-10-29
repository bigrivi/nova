/** `/commit`: show the files and the proposed message, then commit on confirm */
import { useKeyboard } from "@opentui/react";
import { useEffect, useState } from "react";
import { commitChanges, planCommit } from "../../api/git.ts";
import type { NovaCommitPlan } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useToastStore } from "../../stores/toast-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScreenPanel } from "./ScreenPanel.tsx";

const MAX_FILES = 8;

export function CommitScreen() {
    const theme = useTheme();
    const sessionId = useChatStore((state) => state.sessionId);
    const [plan, setPlan] = useState<NovaCommitPlan | null>(null);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        if (!sessionId) {
            setError("No open session");
            return;
        }
        let cancelled = false;
        void planCommit(sessionId)
            .then((next) => {
                if (!cancelled) setPlan(next);
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : String(err));
                }
            });
        return () => {
            cancelled = true;
        };
    }, [sessionId]);

    useKeyboard((key) => {
        if (key.name === "escape" || key.name === "q") {
            useScreenStore.getState().close();
            return;
        }
        if (key.name === "y" && plan && !busy) {
            void run(plan);
        }
    });

    async function run(current: NovaCommitPlan): Promise<void> {
        if (!sessionId) return;
        setBusy(true);
        try {
            const result = await commitChanges(
                sessionId,
                current.message,
                current.files.map((file) => file.path),
            );
            useScreenStore.getState().close();
            useToastStore
                .getState()
                .show(`Committed ${result.commit}: ${result.message}`, 5000);
        } catch (err) {
            setBusy(false);
            setError(err instanceof Error ? err.message : String(err));
        }
    }

    if (!plan) {
        return <ScreenLoading message={error || "Preparing the commit..."} />;
    }

    const shown = plan.files.slice(0, MAX_FILES);
    const rest = plan.files.length - shown.length;

    return (
        <ScreenPanel width="70%">
            <box flexDirection="column" gap={1}>
                <text
                    fg={theme.text.base}
                    content={`Commit ${plan.files.length} file(s)`}
                />
                <box flexDirection="column">
                    {shown.map((file) => (
                        <text
                            key={file.path}
                            fg={theme.text.muted}
                            content={`  ${file.status}  ${file.path}`}
                        />
                    ))}
                    {rest > 0 ? (
                        <text
                            fg={theme.text.faint}
                            content={`  … ${rest} more`}
                        />
                    ) : null}
                </box>
                <text fg={theme.text.base} content={plan.message} />
                {error ? (
                    <text fg={theme.feedback.error} content={error} />
                ) : null}
                <text
                    fg={theme.text.faint}
                    content={
                        busy
                            ? "committing…"
                            : "y commit · esc cancel (nothing is staged until you confirm)"
                    }
                />
            </box>
        </ScreenPanel>
    );
}
