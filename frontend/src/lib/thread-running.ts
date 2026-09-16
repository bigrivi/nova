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
