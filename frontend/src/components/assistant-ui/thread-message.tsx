import { UserMessageAttachments } from "@/components/assistant-ui/attachment";
import { CodeRunTool } from "@/components/assistant-ui/code-run-tool";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import {
    Reasoning,
    ReasoningChainGroup,
    ThinkingIndicator,
} from "@/components/assistant-ui/reasoning";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
    groupPartByType,
    MessagePrimitive,
    useAuiState,
} from "@assistant-ui/react";
import { BotIcon, FileText } from "lucide-react";
import { type FC } from "react";

import { AssistantActionBar, BranchPicker } from "./thread-assistant-actions";
import { MessageError } from "./thread-message-error";

const ASSISTANT_NAME = "Nova";

const ATTACHMENT_RE =
    /^<attachment name=(.*?)>\n([\s\S]*?)\n<\/attachment>\n\n([\s\S]*)$/;

function parseAttachment(text: string): { name: string; text: string } | null {
    const match = text.match(ATTACHMENT_RE);
    if (!match) return null;
    return { name: match[1], text: match[3] };
}

const UserText: FC<{ text: string }> = ({ text }) => {
    const parsed = parseAttachment(text);
    if (parsed) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate font-medium text-muted-foreground">
                        {parsed.name}
                    </span>
                </div>
                {parsed.text && (
                    <div className="wrap-break-word rounded-2xl bg-muted px-4 py-2.5 text-foreground">
                        {parsed.text}
                    </div>
                )}
            </div>
        );
    }
    return <>{text}</>;
};

const UserMessage: FC = () => {
    return (
        <MessagePrimitive.Root
            data-slot="aui_user-message-root"
            className="fade-in slide-in-from-bottom-1 grid animate-in auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 duration-150 [&:where(>*)]:col-start-2"
            data-role="user"
        >
            <UserMessageAttachments />

            <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
                <div className="aui-user-message-content wrap-break-word rounded-2xl bg-muted px-4 py-2.5 text-foreground empty:hidden">
                    <MessagePrimitive.Parts
                        components={{
                            Text: UserText,
                        }}
                    />
                </div>
            </div>
        </MessagePrimitive.Root>
    );
};

const AssistantMessage: FC = () => {
    return (
        <MessagePrimitive.Root
            data-slot="aui_assistant-message-root"
            data-role="assistant"
            className="fade-in slide-in-from-bottom-1 flex animate-in flex-col gap-y-2 duration-150"
        >
            <div className="flex min-w-0 items-center gap-2 leading-none">
                <Avatar
                    size="sm"
                    className="size-6 border border-emerald-200/80 bg-emerald-50 text-emerald-900 shadow-sm after:hidden"
                >
                    <AvatarFallback className="bg-transparent text-emerald-900">
                        <BotIcon className="size-3" />
                    </AvatarFallback>
                </Avatar>
                <span className="text-[12px] font-medium tracking-[0.01em] text-muted-foreground">
                    {ASSISTANT_NAME}
                </span>
            </div>

            <div
                data-slot="aui_assistant-message-content"
                className="wrap-break-word min-w-0 text-foreground leading-relaxed flex flex-col gap-2"
            >
                <MessagePrimitive.GroupedParts
                    groupBy={groupPartByType({
                        reasoning: ["group-chainOfThought", "group-reasoning"],
                        "tool-call": ["group-chainOfThought", "group-tool"],
                    })}
                >
                    {({ part, children }) => {
                        switch (part.type) {
                            case "group-chainOfThought":
                                return (
                                    <ReasoningChainGroup status={part.status}>
                                        {children}
                                    </ReasoningChainGroup>
                                );
                            case "group-reasoning":
                                return <>{children}</>;
                            case "group-tool":
                                return <>{children}</>;
                            case "text":
                                return <MarkdownText />;
                            case "reasoning":
                                return <Reasoning status={part.status} />;
                            case "tool-call": {
                                const { toolUI, ...toolProps } = part;
                                if (part.toolName === "ask_user") return null;
                                if (part.toolName === "code_run")
                                    return <CodeRunTool {...toolProps} />;
                                if (part.toolName === "todo_write")
                                    return null;
                                return (
                                    toolUI ?? <ToolFallback {...toolProps} />
                                );
                            }
                            case "indicator":
                                return <ThinkingIndicator />;
                            default:
                                return null;
                        }
                    }}
                </MessagePrimitive.GroupedParts>
                <MessageError />
            </div>

            <div
                data-slot="aui_assistant-message-footer"
                className="relative min-h-7 pt-1.5"
            >
                <BranchPicker />
                <AssistantActionBar />
            </div>
        </MessagePrimitive.Root>
    );
};

export const ThreadMessage: FC = () => {
    const role = useAuiState((s) => s.message.role);

    if (role === "user") return <UserMessage />;
    return <AssistantMessage />;
};
