"use client";

import { useEffect, useRef } from "react";

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
 * Browser-style page zoom for the desktop shell.
 *
 * Applies CSS `zoom` to the root <html> element so text and layout scale
 * together, like Ctrl/Cmd + / - in a browser. pywebview exposes no native
 * zoom API, so this runs entirely inside the webview.
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
    const zoomRef = useRef(1);

    useEffect(() => {
        zoomRef.current = readStoredZoom();

        function applyZoom(zoom: number) {
            zoomRef.current = zoom;
            document.documentElement.style.zoom = String(zoom);
            try {
                window.localStorage.setItem(STORAGE_KEY, String(zoom));
            } catch {
                // Storage can be unavailable (private mode); zoom still applies for the session.
            }
        }

        function zoomBy(delta: number) {
            const next = Math.round((zoomRef.current + delta) * 10) / 10;
            applyZoom(clampZoom(next));
        }

        applyZoom(zoomRef.current);

        function handleKeyDown(event: KeyboardEvent) {
            if ((!event.metaKey && !event.ctrlKey) || event.altKey) {
                return;
            }

            const key = event.key;
            if (key === "=" || key === "+") {
                event.preventDefault();
                zoomBy(ZOOM_STEP);
            } else if (key === "-") {
                event.preventDefault();
                zoomBy(-ZOOM_STEP);
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
            zoomBy(event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
        }

        window.addEventListener("keydown", handleKeyDown);
        window.addEventListener("wheel", handleWheel, { passive: false });

        return () => {
            window.removeEventListener("keydown", handleKeyDown);
            window.removeEventListener("wheel", handleWheel);
        };
    }, []);
}