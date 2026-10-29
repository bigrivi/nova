/** `/review`: one model pass over the uncommitted diff. Read-only. */
import { useEffect, useState } from "react";
import { reviewChanges } from "../../api/git.ts";
import { useChatStore } from "../../stores/chat-store.ts";
import { useScreenStore } from "../../stores/screen-store.ts";
import { ScreenLoading } from "./ScreenLoading.tsx";
import { ScrollText } from "./ScrollText.tsx";

export function ReviewScreen() {
    const sessionId = useChatStore((state) => state.sessionId);
    const [review, setReview] = useState<string | null>(null);
    const [truncated, setTruncated] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        if (!sessionId) {
            setError("No open session");
            return;
        }
        let cancelled = false;
        void reviewChanges(sessionId)
            .then((result) => {
                if (cancelled) return;
                setReview(result.review);
                setTruncated(result.truncated);
            })
            .catch((err: unknown) => {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : String(err));
                }
            });
        return () => {
            cancelled = true;
        };
    }, [sessionId]);

    if (review === null) {
        return (
            <ScreenLoading message={error || "Reviewing the diff..."} />
        );
    }

    return (
        <ScrollText
            title="Review (uncommitted changes)"
            subtitle={truncated ? "diff was truncated before the review" : undefined}
            lines={review.split("\n")}
            footer="↑↓ scroll · esc close"
            onClose={() => useScreenStore.getState().close()}
        />
    );
}
