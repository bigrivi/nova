/** Session-state SSE: tail server-initiated turns (background-task wakes). */
import { sessionEventsUrl } from "../api/nova-api.ts";
import { getChatState } from "../stores/chat-store.ts";
import {
    consumeOwnActive,
    parkTail,
    resumeChatStream,
} from "./chat-stream.ts";

const RECONNECT_DELAY_MS = 2000;

type SessionFrame = {
    type?: unknown;
    session_id?: unknown;
    state?: unknown;
    active?: unknown;
};

function tail(sessionId: string, parkWhenBusy: boolean): void {
    const state = getChatState();
    if (state.sessionId !== sessionId) {
        return;
    }
    if (consumeOwnActive(sessionId)) {
        return;
    }
    if (state.isStreaming) {
        if (parkWhenBusy) {
            parkTail(sessionId);
        }
        return;
    }
    void resumeChatStream(sessionId);
}

function handleFrame(frame: SessionFrame): void {
    if (frame.type === "snapshot") {
        // Connect/reconnect snapshot: recover a wake turn that went active
        // while the event stream was down. Already-streaming turns are
        // ignored rather than parked (they are not a new wake).
        const active = Array.isArray(frame.active) ? frame.active : [];
        const sessionId = getChatState().sessionId;
        if (sessionId && active.includes(sessionId)) {
            tail(sessionId, false);
        }
        return;
    }
    if (frame.type !== "state" || frame.state !== "active") {
        return;
    }
    const sessionId =
        typeof frame.session_id === "string" ? frame.session_id : "";
    if (sessionId) {
        tail(sessionId, true);
    }
}

function handleRawFrame(frame: string): void {
    const payload = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
    if (!payload) {
        return;
    }
    try {
        handleFrame(JSON.parse(payload) as SessionFrame);
    } catch {
        // Malformed frame; the next event corrects state.
    }
}

/**
 * Subscribe to /api/events and reconnect forever; returns the unsubscribe
 * function. Bun has no global EventSource, so this speaks SSE directly.
 */
export function startSessionEvents(): () => void {
    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let abort: AbortController | null = null;

    async function connect(): Promise<void> {
        abort = new AbortController();
        try {
            const response = await fetch(sessionEventsUrl(), {
                signal: abort.signal,
            });
            if (!response.ok || !response.body) {
                throw new Error(`events stream failed: ${response.status}`);
            }
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            for (;;) {
                const { done, value } = await reader.read();
                buffer += decoder.decode(value ?? new Uint8Array(), {
                    stream: !done,
                });
                let boundary = buffer.indexOf("\n\n");
                while (boundary !== -1) {
                    const frame = buffer.slice(0, boundary);
                    buffer = buffer.slice(boundary + 2);
                    if (frame) {
                        handleRawFrame(frame);
                    }
                    boundary = buffer.indexOf("\n\n");
                }
                if (done) {
                    return;
                }
            }
        } catch {
            // Connection dropped or aborted; reconnect below unless stopped.
        } finally {
            if (!stopped) {
                retryTimer = setTimeout(
                    () => void connect(),
                    RECONNECT_DELAY_MS,
                );
            }
        }
    }

    void connect();

    return () => {
        stopped = true;
        if (retryTimer) {
            clearTimeout(retryTimer);
        }
        abort?.abort();
    };
}
