import { useEffect, useState } from "react";

import { fetchAppVersion, getSpeechStatus } from "../../lib/nova-api";
import { useSpeechStore } from "../../stores/speech-store";

/**
 * Read the backend's startup status once and reflect it in the UI.
 *
 * Two unrelated reads that share a lifetime: the version for the sidebar badge,
 * and the voice state for the microphone control's visibility.
 *
 * The voice half exists because a recording is owned by the backend, not by this
 * view. A take started before a reload outlives the page, so on coming back the
 * composer has to adopt it -- offering cancel/send instead of a start button that
 * the backend would refuse with a 409. The clock is taken from the backend's
 * `recording_since_ms` rather than from `Date.now()`, so the elapsed readout
 * continues from where the take actually began instead of restarting at zero.
 */
export function useStartupStatus(): { appVersion: string | null } {
    const [appVersion, setAppVersion] = useState<string | null>(null);

    useEffect(() => {
        // Both reads resolve after the component may have gone; writing to a
        // store or to state past that point is a leak, not a late update.
        let live = true;
        fetchAppVersion()
            .then((version) => {
                if (live) setAppVersion(version);
            })
            .catch(() => {});
        getSpeechStatus()
            .then((status) => {
                if (!live) {
                    return;
                }
                const speech = useSpeechStore.getState();
                speech.setEnabled(status.enabled);
                if (status.recording) {
                    speech.setPhase(
                        "recording",
                        status.recording_since_ms ?? Date.now(),
                    );
                }
            })
            .catch(() => {});
        return () => {
            live = false;
        };
    }, []);

    return { appVersion };
}
