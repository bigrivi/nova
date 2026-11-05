export type ChatDateBucket = "today" | "yesterday" | "last7Days" | "older";

export const DATE_BUCKETS: readonly ChatDateBucket[] = [
    "today",
    "yesterday",
    "last7Days",
    "older",
];

export const DATE_BUCKET_LABELS: Record<ChatDateBucket, string> = {
    today: "Today",
    yesterday: "Yesterday",
    last7Days: "Last 7 days",
    older: "Older",
};

/** Same local-midnight buckets the web sidebar uses. */
export function dateBucket(
    updatedAt: number,
    now: Date = new Date(),
): ChatDateBucket {
    const start = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
    ).getTime();
    const day = 86_400_000;
    if (updatedAt >= start) {
        return "today";
    }
    if (updatedAt >= start - day) {
        return "yesterday";
    }
    if (updatedAt >= start - day * 7) {
        return "last7Days";
    }
    return "older";
}
