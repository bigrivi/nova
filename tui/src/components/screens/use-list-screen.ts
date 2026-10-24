/** Shared async loading for list screens: one fetch, a ready gate, and a
 *  preselection index computed only after the data arrives. */
import { useEffect, useRef, useState } from "react";

export type LoadedList<T> = {
    items: T[];
    error: string;
};

/**
 * Run *loader* once and capture either its items or its error message.
 *
 * Kept free of React so the success/error contract is testable on its own.
 */
export async function loadList<T>(
    loader: () => Promise<T[]>,
): Promise<LoadedList<T>> {
    try {
        return { items: await loader(), error: "" };
    } catch (error) {
        return {
            items: [],
            error: error instanceof Error ? error.message : String(error),
        };
    }
}

/**
 * The index of the preselected item, clamped to the list.
 *
 * Returns 0 when nothing matches, which is also the correct index for an empty
 * list (the caller renders a loading/empty state instead).
 */
export function resolveInitialIndex<T>(
    items: T[],
    preselect?: (items: T[]) => number,
): number {
    if (!preselect || items.length === 0) {
        return 0;
    }
    return Math.max(0, Math.min(preselect(items), items.length - 1));
}

export type ListScreen<T> = LoadedList<T> & {
    ready: boolean;
    initialIndex: number;
    /** Refetch and re-run the ready gate. */
    reload: () => void;
};

/**
 * Load a list once, exposing a `ready` gate so screens never compute a
 * preselection index against an empty array.
 */
export function useListScreen<T>(
    loader: () => Promise<T[]>,
    preselect?: (items: T[]) => number,
): ListScreen<T> {
    const [state, setState] = useState<LoadedList<T>>({
        items: [],
        error: "",
    });
    const [ready, setReady] = useState(false);
    const [version, setVersion] = useState(0);
    // The loader is usually an inline arrow; pin the first one so a re-render
    // never refetches.
    const loaderRef = useRef(loader);
    loaderRef.current = loader;

    useEffect(() => {
        let cancelled = false;
        void loadList(() => loaderRef.current()).then((next) => {
            if (cancelled) return;
            setState(next);
            setReady(true);
        });
        return () => {
            cancelled = true;
        };
    }, [version]);

    return {
        ...state,
        ready,
        initialIndex: ready ? resolveInitialIndex(state.items, preselect) : 0,
        reload: () => {
            setReady(false);
            setVersion((value) => value + 1);
        },
    };
}
