/** `/diff`: what this session changed, without spending a turn */
import { useEffect, useState } from "react";
import { gitDiff, gitStatus } from "../../api/git.ts";
import type { NovaGitDiff, NovaGitStatus } from "../../api/types.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { useTheme } from "../../context/theme.tsx";
import { diffLineTone } from "../../lib/diff-tone.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScrollText } from "./ScrollText.tsx";

export function DiffScreen() {
    const theme = useTheme();
    const sessionId = useChatStore((state) => state.sessionId);
    const [status, setStatus] = useState<NovaGitStatus | null>(null);
    const [diff, setDiff] = useState<NovaGitDiff | null>(null);
    const [error, setError] = useState("");

    useEffect(() => {
        if (!sessionId) {
            setError("No open session");
            return;
        }
        let cancelled = false;
        void Promise.all([gitStatus(sessionId), gitDiff(sessionId)])
            .then(([nextStatus, nextDiff]) => {
                if (cancelled) return;
                setStatus(nextStatus);
                setDiff(nextDiff);
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

    const close = () => useScreenStore.getState().close();

    if (!status || !diff) {
        return <ScreenLoading message={error || "Loading diff..."} />;
    }

    const files = status.files.length;
    const header = `${status.branch || "(detached)"} · ${files} file(s) changed${
        status.ahead || status.behind
            ? ` · ↑${status.ahead} ↓${status.behind}`
            : ""
    }`;

    return (
        <ScrollText
            title="Diff (working tree vs HEAD)"
            subtitle={header}
            lines={diff.diff ? diff.diff.split("\n") : ["No changes"]}
            tone={(line) => diffLineTone(line, theme)}
            footer={`${diff.truncated ? "… truncated · " : ""}↑↓ scroll · esc close`}
            onClose={close}
        />
    );
}
