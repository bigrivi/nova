/** Load once on mount and apply the result, ignoring a stale one.
 *
 *  The caller owns the error: `load` handles (and reports) its own failures,
 *  because only the caller knows whether a missing value means "nothing to
 *  do" or "fall back to something else".
 */
import { useEffect, useRef, type DependencyList } from "react";

import { logWarn } from "../lib/errors.ts";

export function useAsyncOnMount<T>(
    load: () => Promise<T>,
    apply: (value: T) => void,
    deps: DependencyList = [],
): void {
    const loadRef = useRef(load);
    loadRef.current = load;
    const applyRef = useRef(apply);
    applyRef.current = apply;

    useEffect(() => {
        let cancelled = false;
        void loadRef.current().then(
            (value) => {
                if (!cancelled) {
                    applyRef.current(value);
                }
            },
            (err: unknown) => {
                // The caller reports its own failures; this only keeps a
                // rejected promise from becoming an unhandled rejection.
                logWarn("async load failed", err);
            },
        );
        return () => {
            cancelled = true;
        };
    }, deps);
}
