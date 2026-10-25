/** One-line notice for a server-injected sub-agent report.
 *
 * The body is intentionally not rendered: it is the sub-agent's raw output (or
 * provider error) meant for the model's next turn, not for the transcript.
 */
import { useTheme } from "../context/theme.tsx";
import { parseSubagentNotice } from "../lib/subagent.ts";
import type { TuiMessage } from "../stores/chat-store.ts";

export function SubagentNotice({ message }: { message: TuiMessage }) {
    const theme = useTheme();
    const text =
        message.parts[0]?.type === "text" ? message.parts[0].text : "";
    const notice = parseSubagentNotice(text);
    const failed = notice?.status === "error";
    const status = notice ? (failed ? "Error" : "Done") : "Update";

    return (
        <box flexDirection="row" gap={1} paddingX={2} marginBottom={1}>
            <text fg={theme.muted} content="↩" flexShrink={0} />
            <text fg={theme.muted} content="Subagent" flexShrink={0} />
            {notice ? (
                <text fg={theme.foreground} content={notice.target} flexShrink={0} />
            ) : null}
            <text
                fg={failed ? theme.error : theme.success}
                content={status}
                flexShrink={0}
            />
        </box>
    );
}
