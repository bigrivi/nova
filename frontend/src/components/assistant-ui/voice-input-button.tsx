import {
    CheckIcon,
    Loader2Icon,
    MicIcon,
    XIcon,
} from "lucide-react";
import { type RefObject, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
    cancelSpeechRecording,
    startSpeechRecording,
    stopSpeechRecording,
} from "../../lib/nova-api";
import { formatElapsed } from "../../lib/format-elapsed";
import { useComposerStore } from "../../stores/composer-store";
import { useSpeechStore } from "../../stores/speech-store";

function insertAtCaret(
    composerRef: RefObject<HTMLTextAreaElement | null>,
    insert: string,
) {
    const { setText, text } = useComposerStore.getState();
    const textarea = composerRef.current;
    if (!textarea) {
        setText(text ? `${text} ${insert}` : insert);
        return;
    }
    const start = textarea.selectionStart ?? text.length;
    const end = textarea.selectionEnd ?? text.length;
    const before = text.slice(0, start);
    const after = text.slice(end);
    const spacer =
        before && !before.endsWith(" ") && !before.endsWith("\n") ? " " : "";
    setText(`${before}${spacer}${insert}${after ? ` ${after}` : ""}`);
    requestAnimationFrame(() => {
        const caret = (before + spacer + insert).length;
        textarea.focus();
        textarea.setSelectionRange(caret, caret);
    });
}

/**
 * Voice-input control for the composer footer. Renders nothing unless the
 * backend reports a configured transcription provider.
 *
 * Idle is a single microphone button. A take replaces it with an inline
 * panel: elapsed time, a cancel that discards the audio, and a send that
 * stops recording and drops the transcript at the caret.
 *
 * Recording itself runs in the backend (the desktop webview exposes no
 * microphone API); this component only tracks the phase and places the
 * resulting text.
 */
export function VoiceInputButton({
    composerRef,
}: {
    composerRef: RefObject<HTMLTextAreaElement | null>;
}) {
    const { t } = useTranslation();
    const enabled = useSpeechStore((state) => state.enabled);
    const phase = useSpeechStore((state) => state.phase);
    const startedAt = useSpeechStore((state) => state.startedAt);
    const setPhase = useSpeechStore((state) => state.setPhase);
    const setError = useSpeechStore((state) => state.setError);

    if (!enabled) {
        return null;
    }

    async function start() {
        setError(null);
        setPhase("recording", Date.now());
        try {
            await startSpeechRecording();
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
            setPhase("idle");
        }
    }

    async function send() {
        if (phase !== "recording") {
            return;
        }
        setPhase("transcribing");
        try {
            const transcript = await stopSpeechRecording();
            if (transcript) {
                insertAtCaret(composerRef, transcript);
            }
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        } finally {
            setPhase("idle");
        }
    }

    async function cancel() {
        if (phase !== "recording") {
            return;
        }
        try {
            await cancelSpeechRecording();
        } catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        } finally {
            setPhase("idle");
        }
    }

    if (phase === "idle") {
        return (
            <button
                type="button"
                onClick={() => void start()}
                title={t("composer.voiceInput")}
                aria-label={t("composer.voiceInput")}
                className="flex size-8 shrink-0 items-center justify-center rounded-full text-weak-strong transition-colors hover:bg-muted/60 hover:text-foreground"
            >
                <MicIcon className="size-4" />
            </button>
        );
    }

    return (
        <div className="flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-muted pl-2.5 pr-1">
            <span className="relative flex items-center">
                <MicIcon
                    className="size-4 text-foreground"
                    aria-hidden="true"
                />
                {phase === "recording" ? (
                    <span className="absolute -right-0.5 -bottom-0.5 size-1.5 rounded-full bg-success motion-safe:animate-pulse" />
                ) : null}
            </span>
            {phase === "recording" && startedAt !== null ? (
                <ElapsedTime startedAt={startedAt} />
            ) : (
                <Loader2Icon
                    className="size-4 animate-spin text-weak-strong motion-reduce:animate-none"
                    aria-label={t("composer.voiceTranscribing")}
                />
            )}
            <button
                type="button"
                onClick={() => void cancel()}
                disabled={phase !== "recording"}
                title={t("composer.voiceCancel")}
                aria-label={t("composer.voiceCancel")}
                className="flex size-6 items-center justify-center rounded-full text-weak-strong transition-colors hover:bg-background/60 hover:text-foreground disabled:opacity-40"
            >
                <XIcon className="size-3.5" />
            </button>
            <button
                type="button"
                onClick={() => void send()}
                disabled={phase !== "recording"}
                title={t("composer.voiceSend")}
                aria-label={t("composer.voiceSend")}
                className="flex size-6 items-center justify-center rounded-full text-success transition-colors hover:bg-background/60 disabled:opacity-40"
            >
                <CheckIcon className="size-3.5" />
            </button>
        </div>
    );
}

/** Ticks once a second while a take is in progress. */
function ElapsedTime({ startedAt }: { startedAt: number }) {
    const { t } = useTranslation();
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);
    return (
        <span
            role="timer"
            aria-label={t("composer.voiceElapsed")}
            className="min-w-11 font-medium tabular-nums text-foreground"
        >
            {formatElapsed(startedAt, now)}
        </span>
    );
}

export function VoiceErrorHint() {
    const error = useSpeechStore((state) => state.error);
    if (!error) {
        return null;
    }
    return (
        <span
            role="alert"
            title={error}
            className="max-w-40 truncate text-xs text-danger"
        >
            {error}
        </span>
    );
}
