import { useEffect, useRef } from "react";

import { getLastSequence, sessionEventsUrl } from "../../lib/nova-api";
import { parseSessionFrame } from "../../lib/session-events";
import type { StreamController } from "../../lib/stream-controller";
import {
    nextRunningMap,
    reconcileRunningMap,
} from "../../lib/thread-running";
import { renameThreadTitle } from "../../lib/thread-summary";
import { decideTailOnActive } from "../../lib/thread-tail";
import { useBackgroundTaskStore } from "../../stores/background-task-store";
import { useConversationStore } from "../../stores/conversation-store";
import type { NovaBackgroundTask } from "../../types/nova";

export interface SessionEventsParams {
    controller: StreamController;
    currentThreadIdRef: { current: string };
}

/**
 * Own the single session-events SSE connection: a snapshot of active sessions on
 * connect plus live active/idle deltas as the registry reports them, so a
 * sub-agent auto-wake lights its parent thread instantly. EventSource
 * auto-reconnects and re-sends the snapshot, keeping the map correct.
 *
 * The controller is stable and reads live state internally, so the effect never
 * resubscribes and its dependency list stays honest.
 */
export function useSessionEvents(params: SessionEventsParams): void {
    const { controller, currentThreadIdRef } = params;
    const prevActiveSnapshotRef = useRef(new Set<string>());

    useEffect(() => {
        const source = new EventSource(sessionEventsUrl());

        function applySnapshot(
            active: string[],
            tasks: NovaBackgroundTask[],
        ) {
            const seenNow = new Set(active);
            const seenBefore = prevActiveSnapshotRef.current;
            prevActiveSnapshotRef.current = seenNow;
            useConversationStore.getState().setRunningByThread((previous) =>
                reconcileRunningMap(previous, seenNow, seenBefore, (threadId) =>
                    controller.hasLocalStream(threadId),
                ),
            );
            // Tasks are pushed, not polled: this snapshot is the resync point
            // and the "task" frames below keep it current from here on.
            useBackgroundTaskStore.getState().replaceTasks(tasks);
        }

        function applyDelta(sessionId: string, state: string) {
            const running = state === "active";
            const snapshot = new Set(prevActiveSnapshotRef.current);
            if (running) {
                snapshot.add(sessionId);
            } else {
                snapshot.delete(sessionId);
            }
            prevActiveSnapshotRef.current = snapshot;
            if (!running && controller.hasLocalStream(sessionId)) {
                return;
            }
            useConversationStore
                .getState()
                .setRunningByThread((previous) =>
                    nextRunningMap(previous, sessionId, running),
                );
            // Edge-trigger the tail off the event itself, not off the
            // running-map boolean: if the light is already on (e.g. the
            // previous turn's local stream hasn't cleaned up yet), the map
            // identity doesn't change and no effect would fire, so a
            // server-initiated turn would never be tailed. Active events for
            // streams this client started itself are consumed lighting-only.
            const decision = decideTailOnActive({
                active: running,
                current: sessionId === currentThreadIdRef.current,
                localStream: controller.hasLocalStream(sessionId),
                ownTurn: controller.consumeOwnActive(sessionId),
            });
            if (decision === "tail-now") {
                void controller.resume(sessionId, getLastSequence(sessionId));
            } else if (decision === "park") {
                // A local stream is still draining: park the tail request for
                // the stream's cleanup to consume. Tailing now would race the
                // open stream; doing nothing would miss the turn entirely.
                controller.parkTail(sessionId);
            }
        }

        source.onmessage = (event) => {
            const frame = parseSessionFrame(event.data);
            if (!frame) {
                // Malformed or unactionable frame; the next event corrects state.
                return;
            }
            switch (frame.type) {
                case "snapshot":
                    applySnapshot(frame.active, frame.tasks);
                    break;
                case "state":
                    applyDelta(frame.sessionId, frame.state);
                    break;
                case "task":
                    // A background task was created or changed status. Pushed
                    // over this stream, so no /api/tasks poll is needed.
                    useBackgroundTaskStore.getState().updateTask(frame.task);
                    break;
                case "title":
                    // The background title job finished. Renaming in place
                    // keeps the sidebar from reordering under the cursor; if
                    // this client missed the frame the next load still picks
                    // the title up from /api/sessions.
                    useConversationStore
                        .getState()
                        .setThreads((previous) =>
                            renameThreadTitle(
                                previous,
                                frame.sessionId,
                                frame.title,
                            ),
                        );
                    break;
            }
        };

        // Close the stream when the page is hidden or torn down so the backend
        // is not left holding an orphaned SSE connection.
        const handlePageHide = () => source.close();
        window.addEventListener("pagehide", handlePageHide);

        return () => {
            window.removeEventListener("pagehide", handlePageHide);
            source.close();
        };
    }, [controller, currentThreadIdRef]);
}
