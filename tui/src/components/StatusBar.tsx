/** Bottom status bar: model info + running status */
import { useEffect, useState } from "react";
import { getSessionContext, listModels, listProviders } from "../api/nova-api.ts";
import { useTheme } from "../context/theme.tsx";
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

export function StatusBar() {
    const theme = useTheme();
    const isStreaming = useChatStore((state) => state.isStreaming);
    const provider = useChatStore((state) => state.provider);
    const model = useChatStore((state) => state.model);
    const agentName = useChatStore((state) => state.agentName);
    const [modelName, setModelName] = useState(model);
    const [providerName, setProviderName] = useState(provider);
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

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const [models, providers] = await Promise.all([
                    listModels(),
                    listProviders(),
                ]);
                if (cancelled) return;
                const m = models.find((x) => x.provider === provider && x.model === model);
                const p = providers.find((x) => x.key === provider);
                setModelName(m?.label ?? model);
                setProviderName(p?.name ?? provider);
            } catch {
                if (cancelled) return;
                setModelName(model);
                setProviderName(provider);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [provider, model]);

    const cwd = WORKSPACE_DIR;

    return (
        <box
            flexDirection="column"
            paddingX={2}
            paddingY={0}
            marginTop={0}
            flexShrink={0}
        >
            <box
                flexDirection="row"
                justifyContent="space-between"
                flexShrink={0}
            >
                <box flexDirection="row" flexShrink={0} gap={1} alignItems="center">
                    <text
                        fg={isStreaming ? theme.running : theme.muted}
                        content={isStreaming ? "●" : "○"}
                    />
                    <text fg={theme.accent} content={agentName} />
                    <text fg={theme.subtle} content="·" />
                    <text fg={theme.foreground} content={modelName || model} />
                    <text fg={theme.muted} content={`(${providerName || provider})`} />
                </box>
                <box flexDirection="row" flexShrink={0} gap={1}>
                    <text fg={theme.subtle} content="Ctrl+C exit" />
                    <text fg={theme.subtle} content="·" />
                    <text fg={theme.subtle} content="/commands" />
                </box>
            </box>
            <box flexDirection="row" flexShrink={0} gap={1}>
                <text fg={theme.muted} content="ctx" />
                <text fg={theme.running} content={formatK(used)} />
                <text fg={theme.muted} content="/" />
                <text fg={theme.muted} content={limit ? formatK(limit) : "—"} />
                <text
                    fg={percentColor}
                    content={limit ? `(${percent}%)` : "(—%)"}
                />
                <text fg={theme.subtle} content="·" />
                <text fg={theme.subtle} content={cwd} />
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
