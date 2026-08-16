"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "nova.ui.zoom";
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2;
const ZOOM_STEP = 0.1;

function clampZoom(value: number): number {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function readStoredZoom(): number {
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (raw === null) {
            return 1;
        }
        const value = Number.parseFloat(raw);
        return Number.isFinite(value) ? clampZoom(value) : 1;
    } catch {
        return 1;
    }
}

/**
 * Browser-style zoom scoped to a single element (the thread message list).
 *
 * Applies CSS `zoom` to the element returned by the callback ref so only the
 * messages scale, leaving the sidebar, composer, and dialogs at 100%.
 *
 * Shortcuts:
 *   Cmd/Ctrl + = / +   zoom in
 *   Cmd/Ctrl + -       zoom out
 *   Cmd/Ctrl + 0       reset to 100%
 *   Cmd/Ctrl + scroll  zoom (also covers trackpad pinch)
 *
 * The level is persisted to localStorage and restored on next launch.
 */
export function useZoom() {
    const [zoom, setZoom] = useState(readStoredZoom);
    const zoomRef = useRef(zoom);
    const elementRef = useRef<HTMLDivElement | null>(null);

    function applyZoom(nextZoom: number) {
        zoomRef.current = nextZoom;
        setZoom(nextZoom);
        const element = elementRef.current;
        if (element) {
            element.style.zoom = String(nextZoom);
        }
        try {
            window.localStorage.setItem(STORAGE_KEY, String(nextZoom));
        } catch {
            // Storage can be unavailable (private mode); zoom still applies for the session.
        }
    }

    const zoomTargetRef = useCallback((element: HTMLDivElement | null) => {
        elementRef.current = element;
        if (element) {
            element.style.zoom = String(zoomRef.current);
        }
    }, []);

    useEffect(() => {
        const element = elementRef.current;
        if (element) {
            element.style.zoom = String(zoom);
        }

        function handleKeyDown(event: KeyboardEvent) {
            if ((!event.metaKey && !event.ctrlKey) || event.altKey) {
                return;
            }
            const key = event.key;
            if (key === "=" || key === "+") {
                event.preventDefault();
                applyZoom(
                    clampZoom(
                        Math.round((zoomRef.current + ZOOM_STEP) * 10) / 10,
                    ),
                );
            } else if (key === "-") {
                event.preventDefault();
                applyZoom(
                    clampZoom(
                        Math.round((zoomRef.current - ZOOM_STEP) * 10) / 10,
                    ),
                );
            } else if (key === "0") {
                event.preventDefault();
                applyZoom(1);
            }
        }

        function handleWheel(event: WheelEvent) {
            if (!event.ctrlKey) {
                return;
            }
            event.preventDefault();
            const delta = event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP;
            applyZoom(
                clampZoom(Math.round((zoomRef.current + delta) * 10) / 10),
            );
        }

        window.addEventListener("keydown", handleKeyDown);
        window.addEventListener("wheel", handleWheel, { passive: false });

        return () => {
            window.removeEventListener("keydown", handleKeyDown);
            window.removeEventListener("wheel", handleWheel);
        };
    }, [zoom]);

    return zoomTargetRef;
}
