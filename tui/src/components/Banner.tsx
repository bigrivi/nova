/** Welcome banner — mirrors nova/cli/chat_app.py::_print_banner */
import { useChatStore } from "../stores/chat-store.ts";
import { COMMANDS } from "../commands.ts";
import { theme } from "../theme.ts";

function bannerText(): string {
    const usages = COMMANDS.map((c) => c.usage).filter(Boolean);
    if (usages.length === 0) return "";
    if (usages.length === 1) return `Use ${usages[0]} for commands.`;
    return `Use ${usages.slice(0, -1).join(", ")}, or ${usages[usages.length - 1]} for commands.`;
}

export function Banner() {
    const provider = useChatStore((s) => s.provider);
    const model = useChatStore((s) => s.model);

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
                <text fg={theme.muted} content="Model   " />
                <text fg={theme.foreground} content={model || "—"} />
            </box>
            <box flexDirection="row">
                <text fg={theme.muted} content="Provider    " />
                <text fg={theme.running} content={provider || "—"} />
            </box>
            <box marginTop={1}>
                <text fg={theme.muted} content={bannerText()} />
            </box>
        </box>
    );
}
