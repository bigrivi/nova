import { UserMessageAttachments } from "@/components/assistant-ui/attachment";
import { CodeRunTool } from "@/components/assistant-ui/code-run-tool";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import {
    Reasoning,
    ReasoningChainGroup,
    ThinkingIndicator,
} from "@/components/assistant-ui/reasoning";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";
import { ToolGroup } from "@/components/assistant-ui/tool-group";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
    buildTimelinePathMap,
    createTimelineGroupBy,
    readPartElapsedMs,
} from "@/lib/timeline-grouping";
import { DEFAULT_AGENT_KEY } from "@/lib/nova-constants";
import { MessagePrimitive, useAuiState } from "@assistant-ui/react";
import { BotIcon, ChevronDownIcon, FileText } from "lucide-react";
import { memo, useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useShallow } from "zustand/shallow";

import { cn } from "@/lib/utils";

import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible";

import { AgentAvatar } from "./agent-avatar";
import { AssistantActionBar, BranchPicker } from "./thread-assistant-actions";
import { MessageError } from "./thread-message-error";

function groupIndices(part: { type: string }): readonly number[] {
    return "indices" in part
        ? ((part as { indices?: readonly number[] }).indices ?? [])
        : [];
}

const ATTACHMENT_RE =
    /^<attachment name=(.*?)>\n([\s\S]*?)\n<\/attachment>\n\n([\s\S]*)$/;

const SUBAGENT_RE =
    /^\[subagent:(.+?)\s+status=(done|error)\]\s*\n?([\s\S]*)$/;

type SubagentStatus = "done" | "error";

type ParsedSubagent = {
    target: string;
    status: SubagentStatus;
    body: string;
};

function parseSubagentMessage(text: string): ParsedSubagent | null {
    const match = text.match(SUBAGENT_RE);
    if (!match) return null;
    const target = match[1].trim();
    if (!target) return null;
    return {
        target,
        status: match[2] === "error" ? "error" : "done",
        body: match[3].replace(/^\n+/, ""),
    };
}

function readMessageVariant(message: unknown): string | null {
    if (!message || typeof message !== "object") return null;
    const custom = (message as { metadata?: { custom?: unknown } }).metadata
        ?.custom;
    if (!custom || typeof custom !== "object") return null;
    const variant = (custom as { variant?: unknown }).variant;
    return typeof variant === "string" ? variant : null;
}

function readUserText(message: unknown): string {
    if (!message || typeof message !== "object") return "";
    if ((message as { role?: unknown }).role !== "user") return "";
    const content = (message as { content?: unknown }).content;
    if (typeof content === "string") return content;
    const parts = (message as { parts?: unknown }).parts;
    if (!Array.isArray(parts)) return "";
    return parts
        .filter(
            (part): part is { type: string; text?: unknown } =>
                !!part &&
                typeof part === "object" &&
                (part as { type?: unknown }).type === "text",
        )
        .map((part) => String(part.text ?? ""))
        .join("\n");
}

const SubagentChip: FC<ParsedSubagent> = ({ target, status, body }) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const isError = status === "error";
    return (
        <Collapsible
            open={open}
            onOpenChange={setOpen}
            className={cn(
                "max-w-full overflow-hidden rounded-xl border",
                isError
                    ? "border-rose-200/80 bg-rose-50/40"
                    : "border-[#E4E3DF] bg-muted/40",
            )}
        >
            <CollapsibleTrigger asChild>
                <button
                    type="button"
                    className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 focus-visible:ring-inset"
                >
                    <span aria-hidden="true">{"\u21A9"}</span>
                    {target ? (
                        <span className="truncate font-medium">
                            {t("thread.subagentFrom", { target })}
                        </span>
                    ) : null}
                    <span
                        className={cn(
                            "shrink-0 rounded-full px-2 py-0.5 font-medium",
                            isError
                                ? "bg-rose-100 text-rose-800"
                                : "bg-emerald-100 text-emerald-800",
                        )}
                    >
                        {isError
                            ? t("thread.subagentError")
                            : t("thread.subagentDone")}
                    </span>
                    <span className="ml-auto flex shrink-0 items-center gap-1">
                        <span className="hidden sm:inline">
                            {open
                                ? t("thread.subagentHideDetails")
                                : t("thread.subagentShowDetails")}
                        </span>
                        <ChevronDownIcon
                            className={cn(
                                "size-3.5 transition-transform duration-200 motion-reduce:transition-none",
                                open && "rotate-180",
                            )}
                            aria-hidden="true"
                        />
                    </span>
                </button>
            </CollapsibleTrigger>
            {body ? (
                <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down motion-reduce:data-[state=closed]:animate-none motion-reduce:data-[state=open]:animate-none">
                    <div className="border-t border-[#E4E3DF] px-3 py-2.5">
                        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">
                            {body}
                        </div>
                    </div>
                </CollapsibleContent>
            ) : null}
        </Collapsible>
    );
};

const AssistantText: FC<{ text: string }> = ({ text }) => {
    const parsed = parseSubagentMessage(text);
    if (!parsed) {
        return <MarkdownText />;
    }
    return <SubagentChip {...parsed} />;
};

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
                    <div className="wrap-break-word rounded-2xl border bg-muted px-4 py-2.5 text-foreground">
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
                <div className="aui-user-message-content wrap-break-word rounded-2xl border border-[#E4E3DF] bg-white px-4 py-2.5 text-foreground shadow-[0_2px_8px_rgba(20,20,18,0.04)] empty:hidden">
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

const AssistantMessage: FC<{ name: string; agentKey: string | null }> = ({
    name,
    agentKey,
}) => {
    // The default/main agent keeps the branded bot icon; a named primary agent
    // shows its own identity avatar (same component as the composer's chip).
    const isDefaultAgent = !agentKey || agentKey === DEFAULT_AGENT_KEY;
    const parts = useAuiState(useShallow((s) => s.message.parts));
    const toolUIs = useAuiState((s) => s.tools.toolUIs);
    const groupBy = useMemo(
        () => createTimelineGroupBy(buildTimelinePathMap(parts, { toolUIs })),
        [parts, toolUIs],
    );

    const visibleToolIndices = useMemo(() => {
        const indices = new Set<number>();
        parts.forEach((part, index) => {
            if (part.type !== "tool-call") return;
            const name = part.toolName ?? "";
            if (name === "ask_user" || name === "todo_write") return;
            indices.add(index);
        });
        return indices;
    }, [parts]);

    const countVisibleTools = (indices: readonly number[]) =>
        indices.reduce(
            (total, index) => (visibleToolIndices.has(index) ? total + 1 : total),
            0,
        );

    const segmentElapsedMs = (indices: readonly number[]): number | null => {
        let total = 0;
        let hasElapsed = false;
        for (const index of indices) {
            const part = parts[index];
            if (!part || part.type !== "reasoning") continue;
            const value = readPartElapsedMs(part);
            if (value == null) continue;
            total += value;
            hasElapsed = true;
        }
        return hasElapsed ? total : null;
    };

    return (
        <MessagePrimitive.Root
            data-slot="aui_assistant-message-root"
            data-role="assistant"
            className="fade-in slide-in-from-bottom-1 flex animate-in flex-col gap-y-2 duration-150"
        >
            <div className="flex min-w-0 items-center gap-2 leading-none">
                {isDefaultAgent ? (
                    <Avatar
                        size="sm"
                        className="size-6 border border-emerald-200/80 bg-emerald-50 text-emerald-900 shadow-sm after:hidden"
                    >
                        <AvatarFallback className="bg-transparent text-emerald-900">
                            <BotIcon className="size-3" />
                        </AvatarFallback>
                    </Avatar>
                ) : (
                    <AgentAvatar agentKey={agentKey} name={name} size="lg" />
                )}
                <span className="text-[12px] font-medium tracking-[0.01em] text-muted-foreground">
                    {name}
                </span>
            </div>

            <div
                data-slot="aui_assistant-message-content"
                className="wrap-break-word min-w-0 text-foreground leading-relaxed flex flex-col gap-2"
            >
                <MessagePrimitive.GroupedParts
                    groupBy={groupBy}
                >
                    {({ part, children }) => {
                        switch (part.type) {
                            case "group-chainOfThought":
                                return (
                                    <ReasoningChainGroup
                                        status={part.status}
                                        toolCount={countVisibleTools(
                                            groupIndices(part),
                                        )}
                                        elapsedMs={segmentElapsedMs(
                                            groupIndices(part),
                                        )}
                                    >
                                        {children}
                                    </ReasoningChainGroup>
                                );
                            case "group-reasoning":
                                return <>{children}</>;
                            case "group-tool":
                                return (
                                    <ToolGroup
                                        variant="timeline"
                                        count={countVisibleTools(
                                            groupIndices(part),
                                        )}
                                    >
                                        {children}
                                    </ToolGroup>
                                );
                            case "group-tool-standalone":
                                return (
                                    <ToolGroup
                                        variant="standalone"
                                        count={countVisibleTools(
                                            groupIndices(part),
                                        )}
                                    >
                                        {children}
                                    </ToolGroup>
                                );
                            case "group-blank":
                                return null;
                            case "text":
                                return (
                                    <AssistantText
                                        text={
                                            "text" in part
                                                ? String(
                                                      (
                                                          part as {
                                                              text?: unknown;
                                                          }
                                                      ).text ?? "",
                                                  )
                                                : ""
                                        }
                                    />
                                );
                            case "reasoning":
                                return (
                                    <Reasoning
                                        elapsedMs={readPartElapsedMs(part)}
                                    />
                                );
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

/**
 * Memoised: the message list re-renders on every streamed token, and only the
 * message being written into has new content. Without this, every earlier
 * message in the thread re-renders per token.
 */
export const ThreadMessage = memo(function ThreadMessage({
    assistantName = "Nova",
    assistantAgentKey = null,
}: {
    assistantName?: string;
    assistantAgentKey?: string | null;
}) {
    const role = useAuiState((s) => s.message.role);
    const variant = useAuiState((s) => readMessageVariant(s.message));
    const userText = useAuiState((s) => readUserText(s.message));

    if (role === "user") {
        const parsed = parseSubagentMessage(userText);
        if (variant === "subagent" || parsed) {
            return (
                <div
                    data-role="subagent"
                    className="fade-in slide-in-from-bottom-1 animate-in duration-150"
                >
                    <SubagentChip
                        {...(parsed ?? {
                            target: "",
                            status: "done" as const,
                            body: userText,
                        })}
                    />
                </div>
            );
        }
        return <UserMessage />;
    }
    return (
        <AssistantMessage name={assistantName} agentKey={assistantAgentKey} />
    );
});
