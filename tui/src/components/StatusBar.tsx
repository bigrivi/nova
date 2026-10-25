/** Bottom status bar: two rows, running state on top and environment/help below.
 *
 * Row 1 (dynamic): status dot, model, provider — context usage on the right.
 * Row 2 (static): shortened workspace path, git branch — shortcuts on the right.
 * Optional pieces drop in a fixed order as the terminal narrows; the status dot
 * and model name are always kept.
 */
import { useEffect } from "react";
import { homedir } from "node:os";
import { useTerminalDimensions } from "@opentui/react";
import { getSessionContext } from "../api/nova-api.ts";
import { useTheme } from "../context/theme.tsx";
import {
    modelLabel,
    providerLabel,
} from "../lib/catalog.ts";
import { useApp } from "../context/app.tsx";
import { displayWidth } from "../lib/display-width.ts";
import { deriveAgentStatus, lastAssistantStatus } from "../lib/status.ts";
import {
    SHORTCUTS_COMPACT,
    SHORTCUTS_FULL,
    shortenPath,
    shortcutText,
    statusDensity,
} from "../lib/status-format.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";
import { ContextMeter } from "./status/ContextMeter.tsx";
import { ShortcutHints } from "./status/ShortcutHints.tsx";
import { StatusGlyph } from "./status/StatusGlyph.tsx";
import { StatusLine } from "./status/StatusLine.tsx";

const PADDING_X = 2;

export function StatusBar() {
    const theme = useTheme();
    const dimensions = useTerminalDimensions();
    const contentWidth = Math.max(1, dimensions.width - PADDING_X * 2);

    const isStreaming = useChatStore((state) => state.isStreaming);
    const provider = useChatStore((state) => state.provider);
    const model = useChatStore((state) => state.model);
    const agentName = useChatStore((state) => state.agentName);
    const sessionId = useChatStore((state) => state.sessionId);
    const assistantStatus = useChatStore((state) =>
        lastAssistantStatus(state.messages),
    );
    const hasApproval = useApprovalStore((state) => state.pending !== null);
    const hasQuestion = useAskUserStore((state) => state.active !== null);
    const used = useCtxStore((state) => state.used);
    const limit = useCtxStore((state) => state.limit);
    const percent = useCtxStore((state) => state.percent);

    const catalog = useApp().catalog;
    const app = useApp();
    const branch = app.branch;

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
                if (!cancelled) {
                    useCtxStore
                        .getState()
                        .setCtx(ctx.used, ctx.limit, ctx.percent);
                }
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, [sessionId, isStreaming]);

    const status = deriveAgentStatus({
        isStreaming,
        hasApproval,
        hasQuestion,
        lastAssistantStatus: assistantStatus,
    });
    const density = statusDensity(dimensions.width);
    const shortcuts = density.compactHints
        ? SHORTCUTS_COMPACT
        : SHORTCUTS_FULL;
    const branchText = !density.hideBranch && branch ? `⎇ ${branch}` : "";
    const reserved =
        displayWidth(shortcutText(shortcuts)) +
        2 +
        (branchText ? displayWidth(branchText) + 1 : 0);
    const pathWidth = Math.max(8, contentWidth - reserved);
    const path = shortenPath(WORKSPACE_DIR, homedir(), pathWidth);
    const modelName = modelLabel(catalog, provider, model);
    const providerName = providerLabel(catalog, provider);

    return (
        <box
            flexDirection="column"
            paddingX={PADDING_X}
            paddingY={0}
            marginTop={0}
            flexShrink={0}
            gap={0}
        >
            <StatusLine
                left={
                    <>
                        <StatusGlyph status={status} />
                        <text
                            fg={theme.accent}
                            content={agentName || "main"}
                            wrapMode="none"
                            flexShrink={0}
                        />
                        <text fg={theme.muted} content="·" flexShrink={0} />
                        <text
                            fg={theme.foreground}
                            content={modelName || model || "no model"}
                            wrapMode="none"
                            truncate
                            flexShrink={1}
                            minWidth={0}
                        />
                        {density.hideProvider || !providerName ? null : (
                            <>
                                <text
                                    fg={theme.muted}
                                    content="·"
                                    flexShrink={0}
                                />
                                <text
                                    fg={theme.muted}
                                    content={providerName}
                                    wrapMode="none"
                                    flexShrink={0}
                                />
                            </>
                        )}
                    </>
                }
                right={
                    <ContextMeter
                        used={used}
                        limit={limit}
                        percent={percent}
                        density={density}
                    />
                }
            />
            <StatusLine
                left={
                    <>
                        <text
                            fg={theme.subtle}
                            content={path}
                            wrapMode="none"
                            truncate
                            flexShrink={1}
                            minWidth={0}
                        />
                        {branchText ? (
                            <text
                                fg={theme.muted}
                                content={branchText}
                                wrapMode="none"
                                flexShrink={0}
                            />
                        ) : null}
                    </>
                }
                right={<ShortcutHints shortcuts={shortcuts} />}
            />
        </box>
    );
}
