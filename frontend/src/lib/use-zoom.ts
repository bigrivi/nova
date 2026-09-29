"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "nova.ui.zoom";
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 2;

function clampZoom(value: number): number {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function quantizeZoom(value: number): number {
    return clampZoom(Math.round(value * 10) / 10);
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

function persistZoom(value: number): void {
    try {
        window.localStorage.setItem(STORAGE_KEY, String(value));
    } catch {
        // Storage can be unavailable (private mode); zoom still applies.
    }
}

// Module-level source of truth so the thread view and the settings dialog
// share one level without prop drilling.
let currentZoom =
    typeof window === "undefined" ? 1 : readStoredZoom();
const subscribers = new Set<(zoom: number) => void>();

function notifyZoom(): void {
    for (const notify of subscribers) {
        notify(currentZoom);
    }
}

/** Persist a level and broadcast it to every subscriber. */
export function setZoomLevel(value: number): number {
    const next = quantizeZoom(value);
    if (next === currentZoom) {
        return next;
    }
    currentZoom = next;
    persistZoom(next);
    notifyZoom();
    return next;
}

export function getZoomLevel(): number {
    return currentZoom;
}

function subscribeZoom(notify: (zoom: number) => void): () => void {
    subscribers.add(notify);
    return () => {
        subscribers.delete(notify);
    };
}

/** Reactive zoom value for controls such as the settings slider. */
export function useZoomLevel(): number {
    const [zoom, setZoom] = useState(currentZoom);
    useEffect(() => subscribeZoom(setZoom), []);
    return zoom;
}

/**
 * Browser-style zoom scoped to a single element (the thread message list).
 *
 * Applies CSS `zoom` to the element returned by the callback ref so only the
 * messages scale, leaving the sidebar, composer, and dialogs at 100%.
 *
 * The level is controlled from Settings > General and persisted to
 * localStorage, restored on next launch.
 */
export function useZoom() {
    const elementRef = useRef<HTMLDivElement | null>(null);

    const applyZoom = useCallback((element: HTMLDivElement | null) => {
        if (element) {
            element.style.zoom = String(currentZoom);
        }
    }, []);

    const zoomTargetRef = useCallback(
        (element: HTMLDivElement | null) => {
            elementRef.current = element;
            applyZoom(element);
        },
        [applyZoom],
    );

    useEffect(() => {
        const applyCurrent = () => applyZoom(elementRef.current);
        applyCurrent();
        return subscribeZoom(() => applyCurrent());
    }, [applyZoom]);

    return zoomTargetRef;
}
