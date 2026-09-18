export type RunningMap = Record<string, boolean>;

export function nextRunningMap(
    previous: RunningMap,
    threadId: string,
    running: boolean,
): RunningMap {
    if (!!previous[threadId] === running) {
        return previous;
    }
    if (!running) {
        const next = { ...previous };
        delete next[threadId];
        return next;
    }
    return { ...previous, [threadId]: true };
}

export function isThreadRunning(
    running: RunningMap,
    threadId: string,
): boolean {
    return !!running[threadId];
}

export function runningThreadIds(running: RunningMap): string[] {
    return Object.keys(running).filter((threadId) => running[threadId]);
}

export function reconcileRunningMap(
    previous: RunningMap,
    seenNow: ReadonlySet<string>,
    seenBefore: ReadonlySet<string>,
    hasLocalStream: (threadId: string) => boolean,
): RunningMap {
    // Merge server truth in, then edge-trigger lights out. A thread is only
    // auto-off when it *disappeared* between two consecutive snapshots and has
    // no local stream: a just-submitted session never appeared in a snapshot,
    // so it can never be flickered off while its slot registers.
    let next = previous;
    const ensureCopy = () => {
        if (next === previous) {
            next = { ...previous };
        }
    };
    for (const sessionId of seenNow) {
        if (!next[sessionId]) {
            ensureCopy();
            next[sessionId] = true;
        }
    }
    for (const threadId of Object.keys(next)) {
        if (
            next[threadId] &&
            !seenNow.has(threadId) &&
            seenBefore.has(threadId) &&
            !hasLocalStream(threadId)
        ) {
            ensureCopy();
            delete next[threadId];
        }
    }
    return next;
}
