/**
 * `/api/events` tail: one connection per client, driving titles, active turns
 * and background task snapshots into the stores.
 */
import { openSessionEvents } from "../api/events";
import type { SessionEventFrame } from "../api/types";
import { useSessions } from "../state/sessions";
import { useTasks } from "../state/tasks";
import { tabForSession, useTabs } from "../state/tabs";
import { resumeTurn } from "./stream-runner";

let eventsClose: (() => void) | null = null;

function tailActiveSessions(sessionIds: readonly string[]): void {
    for (const sessionId of sessionIds) {
        const tab = tabForSession(sessionId);
        if (!tab) {
            continue;
        }
        void resumeTurn(tab.id).catch(() => {
            // A tail that cannot start is retried by the next event/snapshot.
        });
    }
}

function handleFrame(frame: SessionEventFrame): void {
    switch (frame.type) {
        case "snapshot":
            useTasks.getState().replace(frame.tasks);
            tailActiveSessions(frame.active);
            return;
        case "state":
            if (frame.state === "active") {
                tailActiveSessions([frame.session_id]);
            }
            return;
        case "title":
            useTabs.getState().setTitle(frame.session_id, frame.title);
            useSessions.getState().updateTitle(frame.session_id, frame.title);
            return;
        case "task":
            useTasks.getState().update(frame.task);
            return;
        default:
            return;
    }
}

export function startSessionEvents(): void {
    eventsClose?.();
    eventsClose = openSessionEvents(handleFrame);
}

export function stopSessionEvents(): void {
    eventsClose?.();
    eventsClose = null;
}
