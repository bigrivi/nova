/* eslint-disable react-hooks/set-state-in-effect */
"use client";

import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import {
    AttachmentPrimitive,
    ComposerPrimitive,
    MessagePrimitive,
    useAui,
    useAuiState,
} from "@assistant-ui/react";
import { FileText, PlusIcon, XIcon } from "lucide-react";
import { useEffect, useState, type FC, type PropsWithChildren } from "react";
import { useTranslation } from "react-i18next";
import { useShallow } from "zustand/shallow";

const useFileSrc = (file: File | undefined) => {
    const [src, setSrc] = useState<string | undefined>(undefined);

    useEffect(() => {
        if (!file) {
            return;
        }

        const objectUrl = URL.createObjectURL(file);
        setSrc(objectUrl);

        return () => {
            URL.revokeObjectURL(objectUrl);
            setSrc(undefined);
        };
    }, [file]);

    return src;
};

const useAttachmentSrc = () => {
    const { file, src } = useAuiState(
        useShallow((s): { file?: File; src?: string } => {
            if (s.attachment.type !== "image") return {};
            if (s.attachment.file) return { file: s.attachment.file };
            const src = s.attachment.content?.filter(
                (c) => c.type === "image",
            )[0]?.image;
            if (!src) return {};
            return { src };
        }),
    );

    return useFileSrc(file) ?? src;
};

type AttachmentPreviewProps = {
    src: string;
};

const AttachmentPreview: FC<AttachmentPreviewProps> = ({ src }) => {
    const { t } = useTranslation();
    const [isLoaded, setIsLoaded] = useState(false);
    return (
        <img
            src={src}
            alt={t("attachment.attachmentPreview")}
            className={cn(
                "block h-auto max-h-[80vh] w-auto max-w-full object-contain",
                isLoaded
                    ? "aui-attachment-preview-image-loaded"
                    : "aui-attachment-preview-image-loading invisible",
            )}
            onLoad={() => setIsLoaded(true)}
        />
    );
};

const AttachmentPreviewDialog: FC<PropsWithChildren> = ({ children }) => {
    const { t } = useTranslation();
    const src = useAttachmentSrc();

    if (!src) return children;

    return (
        <Dialog>
            <DialogTrigger
                className="aui-attachment-preview-trigger cursor-pointer transition-colors hover:bg-accent/50"
                asChild
            >
                {children}
            </DialogTrigger>
            <DialogContent className="aui-attachment-preview-dialog-content p-2 sm:max-w-3xl [&>button]:rounded-full [&>button]:bg-foreground/60 [&>button]:p-1 [&>button]:opacity-100 [&>button]:ring-0! [&_svg]:text-background [&>button]:hover:[&_svg]:text-destructive">
                <DialogTitle className="aui-sr-only sr-only">
                    {t("attachment.imageAttachmentPreview")}
                </DialogTitle>
                <div className="aui-attachment-preview relative mx-auto flex max-h-[80dvh] w-full items-center justify-center overflow-hidden bg-background">
                    <AttachmentPreview src={src} />
                </div>
            </DialogContent>
        </Dialog>
    );
};

const AttachmentThumb: FC = () => {
    const { t } = useTranslation();
    const src = useAttachmentSrc();

    return (
        <Avatar className="aui-attachment-tile-avatar h-full w-full rounded-none">
            <AvatarImage
                src={src}
                alt={t("attachment.attachmentPreview")}
                className="aui-attachment-tile-image object-cover"
            />
            <AvatarFallback>
                <FileText className="aui-attachment-tile-fallback-icon size-8 text-muted-foreground" />
            </AvatarFallback>
        </Avatar>
    );
};

const AttachmentUI: FC = () => {
    const { t } = useTranslation();
    const aui = useAui();
    const isComposer = aui.attachment.source !== "message";

    const isImage = useAuiState((s) => s.attachment.type === "image");
    const typeLabel = useAuiState((s) => {
        const type = s.attachment.type;
        switch (type) {
            case "image":
                return t("attachment.image");
            case "document":
                return t("attachment.document");
            case "file":
                return t("attachment.file");
            default:
                return type;
        }
    });

    return (
        <Tooltip>
            <AttachmentPrimitive.Root
                className={cn(
                    "aui-attachment-root relative",
                    isImage &&
                        "aui-attachment-root-composer only:*:first:size-24",
                )}
            >
                <AttachmentPreviewDialog>
                    <TooltipTrigger asChild>
                        <div
                            className="aui-attachment-tile size-14 cursor-pointer overflow-hidden rounded-[calc(var(--composer-radius)-var(--composer-padding))] border bg-muted transition-opacity hover:opacity-75"
                            role="button"
                            tabIndex={0}
                            aria-label={`${typeLabel} attachment`}
                        >
                            <AttachmentThumb />
                        </div>
                    </TooltipTrigger>
                </AttachmentPreviewDialog>
                {isComposer && <AttachmentRemove />}
            </AttachmentPrimitive.Root>
            <TooltipContent side="top">
                <AttachmentPrimitive.Name />
            </TooltipContent>
        </Tooltip>
    );
};

const AttachmentRemove: FC = () => {
    const { t } = useTranslation();
    return (
        <AttachmentPrimitive.Remove asChild>
            <TooltipIconButton
                tooltip={t("attachment.removeFile")}
                className="aui-attachment-tile-remove absolute end-1.5 top-1.5 size-3.5 rounded-full bg-white text-muted-foreground opacity-100 shadow-sm hover:bg-white! [&_svg]:text-black hover:[&_svg]:text-destructive"
                side="top"
            >
                <XIcon className="aui-attachment-remove-icon size-3" />
            </TooltipIconButton>
        </AttachmentPrimitive.Remove>
    );
};

export const UserMessageAttachments: FC = () => {
    return (
        <div className="aui-user-message-attachments-end col-span-full col-start-1 row-start-1 flex w-full flex-row justify-end gap-2">
            <MessagePrimitive.Attachments>
                {() => <AttachmentUI />}
            </MessagePrimitive.Attachments>
        </div>
    );
};

export const ComposerAttachments: FC = () => {
    return (
        <div className="aui-composer-attachments flex w-full flex-row items-center gap-2 overflow-x-auto empty:hidden">
            <ComposerPrimitive.Attachments>
                {() => <AttachmentUI />}
            </ComposerPrimitive.Attachments>
        </div>
    );
};

export const ComposerAddAttachment: FC = () => {
    const { t } = useTranslation();
    return (
        <ComposerPrimitive.AddAttachment
            className="aui-composer-add-attachment size-8 rounded-full p-1 font-semibold text-xs hover:bg-muted-foreground/15 flex items-center justify-center"
            aria-label={t("attachment.addAttachment")}
        >
            <PlusIcon className="aui-attachment-add-icon size-5 stroke-[1.5px]" />
        </ComposerPrimitive.AddAttachment>
    );
};
