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
import { type FC, useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Volume2Icon, PauseIcon, Loader2Icon } from "lucide-react";
import { getTtsStatus, synthesizeTts } from "@/lib/nova-api";

export const AssistantActionBar: FC = () => {
    const { t } = useTranslation();
    const isLast = useAuiState((state) => state.message.isLast);
    const content = useAuiState((state) => state.message.content);
    const text = Array.isArray(content)
        ? content
              .filter((p: any) => p?.type === "text" && typeof p?.text === "string")
              .map((p: any) => p.text)
              .join("\n")
              .trim()
        : "";
    const [ttsEnabled, setTtsEnabled] = useState(false);
    const [playing, setPlaying] = useState(false);
    const [loading, setLoading] = useState(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const urlRef = useRef<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        void getTtsStatus().then((s) => {
            if (!cancelled) setTtsEnabled(Boolean(s.enabled));
        });
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        return () => {
            if (audioRef.current) {
                audioRef.current.pause();
                audioRef.current = null;
            }
            if (urlRef.current) {
                URL.revokeObjectURL(urlRef.current);
                urlRef.current = null;
            }
        };
    }, []);

    const togglePlay = async () => {
        if (playing && audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
            setPlaying(false);
            return;
        }
        if (!text) return;
        setLoading(true);
        try {
            const url = await synthesizeTts(text);
            urlRef.current = url;
            const audio = new Audio(url);
            audioRef.current = audio;
            audio.onended = () => {
                setPlaying(false);
                if (urlRef.current) {
                    URL.revokeObjectURL(urlRef.current);
                    urlRef.current = null;
                }
            };
            await audio.play();
            setPlaying(true);
        } catch (e) {
            // eslint-disable-next-line no-console
            console.error("TTS failed", e);
        } finally {
            setLoading(false);
        }
    };

    return (
        <ActionBarPrimitive.Root
            hideWhenRunning
            autohide="not-last"
            className="aui-assistant-action-bar-root absolute left-0 top-1.5 flex items-center gap-1 text-muted-foreground"
        >
            {ttsEnabled ? (
                <TooltipIconButton tooltip={t("common.play", "Play")} onClick={() => void togglePlay()}>
                    {loading ? (
                        <Loader2Icon className="animate-spin" />
                    ) : playing ? (
                        <PauseIcon />
                    ) : (
                        <Volume2Icon />
                    )}
                </TooltipIconButton>
            ) : null}
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
