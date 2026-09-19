import { useEffect, useRef, useState } from "react";

import { NARROW_VIEWPORT_QUERY } from "../../lib/nova-constants";

export interface ViewportControls {
    isNarrowViewport: boolean;
    isSidebarCollapsed: boolean;
    setIsSidebarCollapsed: (collapsed: boolean) => void;
    collapseSidebarOnNarrowViewport: () => void;
}

/**
 * Track the narrow-viewport media query and drive the sidebar collapse state:
 * auto-collapse when the layout first becomes narrow, and expose a helper to
 * collapse after navigation on narrow screens.
 */
export function useViewport(): ViewportControls {
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(
        () => window.matchMedia(NARROW_VIEWPORT_QUERY).matches,
    );
    const [isNarrowViewport, setIsNarrowViewport] = useState(
        () => window.matchMedia(NARROW_VIEWPORT_QUERY).matches,
    );
    const wasNarrowViewportRef = useRef(isNarrowViewport);

    useEffect(() => {
        const query = window.matchMedia(NARROW_VIEWPORT_QUERY);
        const update = () => setIsNarrowViewport(query.matches);
        update();
        query.addEventListener("change", update);
        return () => query.removeEventListener("change", update);
    }, []);

    useEffect(() => {
        if (isNarrowViewport && !wasNarrowViewportRef.current) {
            setIsSidebarCollapsed(true);
        }
        wasNarrowViewportRef.current = isNarrowViewport;
    }, [isNarrowViewport]);

    function collapseSidebarOnNarrowViewport() {
        if (isNarrowViewport) {
            setIsSidebarCollapsed(true);
        }
    }

    return {
        isNarrowViewport,
        isSidebarCollapsed,
        setIsSidebarCollapsed,
        collapseSidebarOnNarrowViewport,
    };
}
