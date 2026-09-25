import { useEffect, useState } from "react";

import { NARROW_VIEWPORT_QUERY } from "../../lib/nova-constants";

export interface ViewportControls {
    isNarrowViewport: boolean;
    isSidebarCollapsed: boolean;
    setIsSidebarCollapsed: (collapsed: boolean) => void;
    collapseSidebarOnNarrowViewport: () => void;
}

/**
 * Drive the sidebar from the viewport breakpoint until the user expresses a
 * preference, then honour that preference for good.
 *
 * `preference` is null until the user collapses or expands the sidebar by hand
 * (or taps a thread on a narrow screen). While null the sidebar follows the
 * viewport: collapsed below the breakpoint, expanded above it. Once set, the
 * breakpoint no longer has any say, so a manually closed sidebar stays closed
 * at every window size until the user opens it again.
 */
export function useViewport(): ViewportControls {
    const [isNarrowViewport, setIsNarrowViewport] = useState(
        () => window.matchMedia(NARROW_VIEWPORT_QUERY).matches,
    );
    const [preference, setPreference] = useState<boolean | null>(null);

    useEffect(() => {
        const query = window.matchMedia(NARROW_VIEWPORT_QUERY);
        const update = (event: MediaQueryListEvent) =>
            setIsNarrowViewport(event.matches);
        query.addEventListener("change", update);
        return () => query.removeEventListener("change", update);
    }, []);

    return {
        isNarrowViewport,
        isSidebarCollapsed: preference ?? isNarrowViewport,
        setIsSidebarCollapsed: setPreference,
        collapseSidebarOnNarrowViewport() {
            if (isNarrowViewport) {
                setPreference(true);
            }
        },
    };
}
