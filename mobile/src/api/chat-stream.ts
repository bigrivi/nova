/**
 * The chat turn transport.
 *
 * `react-native-sse` speaks POST SSE through XMLHttpRequest, which is what lets
 * the request carry the Basic header and the JSON body. This module owns only
 * the connection and Nova's resume cursor; all frame handling lives in
 * `lib/stream-runner.ts`.
 */
import EventSource from "react-native-sse";

import { apiUrl, authHeader } from "./client";
import type { NovaAttachmentData, NovaStreamEvent } from "./types";

export type ChatStreamOptions = {
    sessionId: string | null;
    message: string;
    displayText?: string;
    provider?: string;
    model?: string;
    agentKey?: string;
    projectId?: string | null;
    reasoningEffort?: string | null;
    attachments?: NovaAttachmentData[];
    regenerate?: boolean;
    resumeFromSequence?: number | null;
    onEvent: (event: NovaStreamEvent) => void;
    onSequence?: (sequence: number) => void;
    onSession?: (sessionId: string) => void;
    onDone: (reason: "done" | "error", message?: string) => void;
};

export type ChatStreamHandle = {
    close: () => void;
    sessionId: () => string | null;
};

const MAX_RETRIES = 2;

export function openChatStream(
    options: ChatStreamOptions,
): ChatStreamHandle {
    let closed = false;
    let completed = false;
    let sessionId = options.sessionId;
    let lastSequence = options.resumeFromSequence ?? null;
    let attempts = 0;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let watchdog: ReturnType<typeof setInterval> | null = null;
    let lastActivity = Date.now();

    const stopWatchdog = () => {
        if (watchdog !== null) {
            clearInterval(watchdog);
            watchdog = null;
        }
    };

    const finish = (reason: "done" | "error", message?: string) => {
        if (completed || closed) {
            return;
        }
        completed = true;
        stopWatchdog();
        if (retryTimer !== null) {
            clearTimeout(retryTimer);
            retryTimer = null;
        }
        source?.close();
        source = null;
        options.onDone(reason, message);
    };

    const connect = (resume: boolean) => {
        if (closed || completed) {
            return;
        }
        const path =
            options.regenerate && !resume
                ? `/api/sessions/${encodeURIComponent(sessionId ?? "")}/regenerate`
                : "/api/chat/stream";
        const body = resume
            ? {
                  session_id: sessionId ?? undefined,
                  message: "",
                  resume_from_seq: lastSequence ?? undefined,
              }
            : options.regenerate
              ? {
                    session_id: sessionId ?? undefined,
                    message: "",
                    regenerate: true,
                    provider: options.provider || undefined,
                    model: options.model || undefined,
                    reasoning_effort: options.reasoningEffort || undefined,
                }
              : {
                  session_id: sessionId ?? undefined,
                  message: options.message,
                  display_text: options.displayText,
                  provider: options.provider || undefined,
                  model: options.model || undefined,
                  agent_key: options.agentKey || undefined,
                  project_id: options.projectId || undefined,
                  reasoning_effort: options.reasoningEffort || undefined,
                  attachments: options.attachments ?? [],
              };

        const next = new EventSource(apiUrl(path), {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "text/event-stream",
                ...authHeader(),
            },
            body: JSON.stringify(body),
            pollingInterval: 0,
            timeout: 0,
            lineEndingCharacter: "\n",
        });
        source = next;
        lastActivity = Date.now();
        if (watchdog === null) {
            watchdog = setInterval(() => {
                if (
                    !completed &&
                    !closed &&
                    Date.now() - lastActivity > 180_000
                ) {
                    finish("error", "The stream stalled");
                }
            }, 30_000);
        }

        next.addEventListener("open", () => {
            lastActivity = Date.now();
        });

        next.addEventListener("message", (event) => {
            if (event.type !== "message") {
                return;
            }
            lastActivity = Date.now();
            const raw = event.data;
            if (raw === null || raw === "") {
                return;
            }
            if (raw === "[DONE]") {
                finish("done");
                return;
            }

            let parsed: NovaStreamEvent;
            try {
                parsed = JSON.parse(raw) as NovaStreamEvent;
            } catch {
                return;
            }

            const sequence = Number(event.lastEventId);
            if (Number.isSafeInteger(sequence) && sequence > 0) {
                lastSequence = sequence;
                parsed.sequence = sequence;
                options.onSequence?.(sequence);
            }

            if (parsed.type === "data-nova-session") {
                const announced = String(parsed.data?.sessionId ?? "");
                if (announced) {
                    sessionId = announced;
                    options.onSession?.(announced);
                }
            }

            if (parsed.type === "error") {
                finish("error", parsed.errorText || "The turn failed");
                return;
            }
            if (parsed.type === "finish" || parsed.type === "abort") {
            }

            options.onEvent(parsed);
        });

        next.addEventListener("error", (event) => {
            if (closed || completed) {
                return;
            }
            let message =
                event.type === "error" && "message" in event
                    ? event.message
                    : "Connection lost";
            const status =
                event.type === "error" && "xhrStatus" in event
                    ? event.xhrStatus
                    : 0;
            if (status === 401) {
                message = "Authentication required";
            } else {
                try {
                    const payload = JSON.parse(message) as {
                        detail?: unknown;
                    };
                    if (typeof payload.detail === "string") {
                        message = payload.detail;
                    }
                } catch {
                    // The body was not JSON; keep the library's message.
                }
            }
            next.close();
            if (source === next) {
                source = null;
            }
            if (sessionId && lastSequence !== null && attempts < MAX_RETRIES) {
                attempts += 1;
                retryTimer = setTimeout(
                    () => connect(true),
                    800 * attempts,
                );
                return;
            }
            finish("error", message);
        });

        // `react-native-sse` 1.2.1 has no server-close event: it stops polling
        // when the XHR reaches DONE. Nova always ends a turn with `[DONE]`,
        // `finish`, `abort` or `error`, which are handled above, so there is
        // nothing to listen for here.
    };

    connect(options.resumeFromSequence != null);

    return {
        close: () => {
            closed = true;
            stopWatchdog();
            if (retryTimer !== null) {
                clearTimeout(retryTimer);
                retryTimer = null;
            }
            source?.close();
            source = null;
        },
        sessionId: () => sessionId,
    };
}
