/** Welcome banner — mirrors nova/cli/chat_app.py::_print_banner */
import { COMMANDS } from "../commands.ts";
import { useTheme } from "../context/theme.tsx";
import { shortenPath } from "../lib/status-format.ts";
import { modelLabel, providerLabel } from "../lib/catalog.ts";
import { useApp } from "../context/app.tsx";
import { useChatStore } from "../stores/chat-store.ts";
import { WORKSPACE_DIR } from "../workspace.ts";

function bannerText(): string {
    const usages = COMMANDS.map((c) => c.usage).filter(Boolean);
    if (usages.length === 0) return "";
    if (usages.length === 1) return `Use ${usages[0]} for commands.`;
    return `Use ${usages.slice(0, -1).join(", ")}, or ${usages[usages.length - 1]} for commands.`;
}

export function Banner() {
    const theme = useTheme();
    const provider = useChatStore((s) => s.provider);
    const model = useChatStore((s) => s.model);
    const catalog = useApp().catalog;
    const modelName = modelLabel(catalog, provider, model);
    const providerName = providerLabel(catalog, provider);
    const home = process.env.HOME || "";
    const cwd = shortenPath(WORKSPACE_DIR, home, 60);

    return (
        <box
            flexDirection="column"
            border
            borderStyle="rounded"
            borderColor={theme.border}
            paddingX={2}
            paddingY={1}
            marginBottom={1}
        >
            <text fg={theme.accent} content="Nova TUI  v0.1.0" />
            <box flexDirection="row" marginTop={1}>
                <box width={14} flexShrink={0}>
                    <text fg={theme.muted} content="Model" />
                </box>
                <text fg={theme.foreground} content={modelName || model || "—"} />
            </box>
            <box flexDirection="row">
                <box width={14} flexShrink={0}>
                    <text fg={theme.muted} content="Provider" />
                </box>
                <text fg={theme.foreground} content={providerName || provider || "—"} />
            </box>
            <box flexDirection="row">
                <box width={14} flexShrink={0}>
                    <text fg={theme.muted} content="工作空间目录" />
                </box>
                <text fg={theme.foreground} content={cwd} />
            </box>
            <box marginTop={1}>
                <text fg={theme.muted} content={bannerText()} />
            </box>
        </box>
    );
}
