/**
 * `/api/events` subscription: server-pushed session state, titles and tasks.
 *
 * Unlike the chat stream this is a GET, so the library's own reconnect loop is
 * enough. The server sends a fresh snapshot on every connect.
 */
import EventSource from "react-native-sse";

import { apiUrl, authHeader } from "./client";
import type { SessionEventFrame } from "./types";

export function openSessionEvents(
    onFrame: (frame: SessionEventFrame) => void,
    onError?: (message: string) => void,
): () => void {
    const source = new EventSource(apiUrl("/api/events"), {
        headers: {
            Accept: "text/event-stream",
            ...authHeader(),
        },
        pollingInterval: 5000,
        timeout: 0,
        lineEndingCharacter: "\n",
    });

    source.addEventListener("message", (event) => {
        if (event.type !== "message" || !event.data) {
            return;
        }
        let frame: SessionEventFrame;
        try {
            frame = JSON.parse(event.data) as SessionEventFrame;
        } catch {
            return;
        }
        if (
            frame.type === "snapshot" ||
            frame.type === "state" ||
            frame.type === "task" ||
            frame.type === "title"
        ) {
            onFrame(frame);
        }
    });

    source.addEventListener("error", (event) => {
        if (event.type === "error" && "message" in event) {
            onError?.(event.message);
        }
    });

    return () => source.close();
}
