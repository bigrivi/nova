/** Welcome banner — mirrors nova/cli/chat_app.py::_print_banner */
import { useChatStore } from "../stores/chat-store.ts";
import { COMMANDS } from "../commands.ts";
import { useTheme } from "../context/theme.tsx";
import { WORKSPACE_DIR } from "../workspace.ts";
import { shortenPath } from "../lib/status-format.ts";

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
                <box width={10} flexShrink={0}>
                    <text fg={theme.muted} content="Model" />
                </box>
                <text fg={theme.foreground} content={model || "—"} />
            </box>
            <box flexDirection="row">
                <box width={10} flexShrink={0}>
                    <text fg={theme.muted} content="Provider" />
                </box>
                <text fg={theme.muted} content={provider || "—"} />
            </box>
            <box flexDirection="row">
                <box width={10} flexShrink={0}>
                    <text fg={theme.muted} content="Cwd" />
                </box>
                <text fg={theme.foreground} content={cwd} />
            </box>
            <box marginTop={1}>
                <text fg={theme.muted} content={bannerText()} />
            </box>
        </box>
    );
}
