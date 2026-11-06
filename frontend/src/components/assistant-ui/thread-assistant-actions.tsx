import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import {
    ActionBarMorePrimitive,
    ActionBarPrimitive,
    AuiIf,
    useAuiState,
} from "@assistant-ui/react";
import {
    CheckIcon,
    CopyIcon,
    DownloadIcon,
    MoreHorizontalIcon,
    RefreshCwIcon,
} from "lucide-react";
import { type FC } from "react";
import { useTranslation } from "react-i18next";

export const AssistantActionBar: FC = () => {
    const { t } = useTranslation();
    // The bar itself still appears on hover for every message (copy/export are
    // useful on history), but regenerate only exists for the newest answer.
    const isLast = useAuiState((state) => state.message.isLast);
    return (
        <ActionBarPrimitive.Root
            hideWhenRunning
            autohide="not-last"
            className="aui-assistant-action-bar-root absolute left-0 top-1.5 flex items-center gap-1 text-muted-foreground"
        >
            <ActionBarPrimitive.Copy asChild>
                <TooltipIconButton tooltip={t("common.copy")}>
                    <AuiIf condition={(s) => s.message.isCopied}>
                        <CheckIcon />
                    </AuiIf>
                    <AuiIf condition={(s) => !s.message.isCopied}>
                        <CopyIcon />
                    </AuiIf>
                </TooltipIconButton>
            </ActionBarPrimitive.Copy>
            {isLast ? (
                <ActionBarPrimitive.Reload asChild>
                    <TooltipIconButton tooltip={t("common.regenerate")}>
                        <RefreshCwIcon />
                    </TooltipIconButton>
                </ActionBarPrimitive.Reload>
            ) : null}
            <ActionBarMorePrimitive.Root>
                <ActionBarMorePrimitive.Trigger asChild>
                    <TooltipIconButton
                        tooltip={t("common.more")}
                        className="data-[state=open]:bg-accent"
                    >
                        <MoreHorizontalIcon />
                    </TooltipIconButton>
                </ActionBarMorePrimitive.Trigger>
                <ActionBarMorePrimitive.Content
                    side="bottom"
                    align="start"
                    className="aui-action-bar-more-content z-50 min-w-32 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
                >
                    <ActionBarPrimitive.ExportMarkdown asChild>
                        <ActionBarMorePrimitive.Item className="aui-action-bar-more-item flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground">
                            <DownloadIcon className="size-4" />
                            {t("thread.exportAsMarkdown")}
                        </ActionBarMorePrimitive.Item>
                    </ActionBarPrimitive.ExportMarkdown>
                </ActionBarMorePrimitive.Content>
            </ActionBarMorePrimitive.Root>
        </ActionBarPrimitive.Root>
    );
};
