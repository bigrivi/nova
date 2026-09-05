/** Bottom status bar: model info + running status */
import { useEffect } from "react";
import { getSessionContext } from "../api/nova-api.ts";
import { StatusActivityIndicator } from "./StatusActivityIndicator.tsx";
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { theme } from "../theme.ts";

export function StatusBar() {
    const isStreaming = useChatStore((state) => state.isStreaming);
    const provider = useChatStore((state) => state.provider);
    const model = useChatStore((state) => state.model);
    const sessionId = useChatStore((state) => state.sessionId);
    const used = useCtxStore((state) => state.used);
    const limit = useCtxStore((state) => state.limit);
    const percent = useCtxStore((state) => state.percent);
    const percentColor =
        percent >= 80
            ? theme.error
            : percent >= 60
              ? theme.running
              : theme.muted;

    // Live turns are driven by SSE data-nova-context; only refresh from /context
    // on history load / session switch, so the fetch never fights the live value.
    useEffect(() => {
        if (!sessionId) {
            useCtxStore.getState().clear();
            return;
        }
        if (isStreaming) return;
        let cancelled = false;
        void getSessionContext(sessionId)
            .then((ctx) => {
                if (!cancelled)
                    useCtxStore
                        .getState()
                        .setCtx(ctx.used, ctx.limit, ctx.percent);
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, [sessionId, isStreaming]);

    return (
        <box
            flexDirection="row"
            justifyContent="space-between"
            paddingX={2}
            paddingY={0}
            marginTop={0}
            flexShrink={0}
        >
            <box flexDirection="row" flexShrink={0} gap={1} alignItems="center">
                {isStreaming ? <StatusActivityIndicator /> : null}
                <text
                    fg={isStreaming ? theme.running : theme.muted}
                    content={isStreaming ? "●" : "○"}
                />
                <text fg={theme.foreground} content={model} />
                <text fg={theme.muted} content={provider} />
                <text fg={theme.subtle} content="·" />
                <text fg={theme.muted} content="ctx" />
                <text fg="#d29922" content={formatK(used)} />
                <text fg={theme.muted} content="/" />
                <text fg={theme.muted} content={limit ? formatK(limit) : "—"} />
                <text
                    fg={percentColor}
                    content={limit ? `${percent}%` : "—%"}
                />
            </box>
            <box flexDirection="row" flexShrink={0} gap={1}>
                <text fg={theme.subtle} content="Ctrl+C exit" />
                <text fg={theme.subtle} content="·" />
                <text fg={theme.subtle} content="/ for commands" />
            </box>
        </box>
    );
}

function formatK(n: number): string {
    if (n >= 1000) {
        const k = n / 1000;
        return `${k.toFixed(1).replace(/\.0$/, "")}k`;
    }
    return String(n);
}
