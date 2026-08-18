import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { cn } from "@/lib/utils";
import {
    ActionBarMorePrimitive,
    ActionBarPrimitive,
    AuiIf,
    BranchPickerPrimitive,
} from "@assistant-ui/react";
import {
    CheckIcon,
    ChevronLeftIcon,
    ChevronRightIcon,
    CopyIcon,
    DownloadIcon,
    MoreHorizontalIcon,
    RefreshCwIcon,
} from "lucide-react";
import { type FC } from "react";
import { useTranslation } from "react-i18next";

export const AssistantActionBar: FC = () => {
    const { t } = useTranslation();
    return (
        <ActionBarPrimitive.Root
            hideWhenRunning
            autohide="not-last"
            className="aui-assistant-action-bar-root absolute left-0 top-1.5 flex gap-1 text-muted-foreground"
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
            <ActionBarPrimitive.Reload asChild>
                <TooltipIconButton tooltip={t("common.refresh")}>
                    <RefreshCwIcon />
                </TooltipIconButton>
            </ActionBarPrimitive.Reload>
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

export const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({
    className,
    ...rest
}) => {
    const { t } = useTranslation();
    return (
        <BranchPickerPrimitive.Root
            hideWhenSingleBranch
            className={cn(
                "aui-branch-picker-root -ms-2 me-2 inline-flex items-center text-muted-foreground text-xs",
                className,
            )}
            {...rest}
        >
            <BranchPickerPrimitive.Previous asChild>
                <TooltipIconButton tooltip={t("common.previous")}>
                    <ChevronLeftIcon />
                </TooltipIconButton>
            </BranchPickerPrimitive.Previous>
            <span className="aui-branch-picker-state font-medium">
                <BranchPickerPrimitive.Number /> /{" "}
                <BranchPickerPrimitive.Count />
            </span>
            <BranchPickerPrimitive.Next asChild>
                <TooltipIconButton tooltip={t("common.next")}>
                    <ChevronRightIcon />
                </TooltipIconButton>
            </BranchPickerPrimitive.Next>
        </BranchPickerPrimitive.Root>
    );
};
