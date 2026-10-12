import { useCallback, useEffect, useRef } from "react";

import { setSessionRoute, updateAgent } from "../../lib/nova-api";

/** Split `"<provider>:<model>"` into the two values both writers send. */
function routeOf(selectedModelId: string | null): {
    provider: string | null;
    model: string | null;
} {
    const parts = selectedModelId ? selectedModelId.split(":") : [];
    return { provider: parts[0] ?? null, model: parts[1] ?? null };
}

/**
 * Push every explicit model pick to the agent, whose row is the default a
 * brand-new conversation starts from.
 *
 * The one case that must not push is a restore: reopening a conversation writes
 * the route back into the UI, and those writes travel out through here. Without
 * suppression, reopening a conversation whose route happens to match the agent's
 * current default would push that default back over the conversation's own
 * record -- a write that looks like nothing and erases what it ran with.
 *
 * The flag is consumed by a single skip rather than cleared on a timer, so the
 * next genuine change is genuine. Hence `beginRestore`, which the caller invokes
 * when it is the one restoring rather than the user picking.
 *
 * The key deliberately excludes the conversation: re-rendering the same pick
 * must not re-push, and that comparison is the only thing standing between a
 * parent re-render and a write.
 */
export function useAgentRouteSync({
    agentKey,
    selectedModelId,
    reasoningEffort,
}: {
    agentKey: string;
    selectedModelId: string | null;
    reasoningEffort: string | null;
}): { beginRestore: () => void } {
    const restoring = useRef(false);
    const pushed = useRef("");
    const { provider, model } = routeOf(selectedModelId);

    useEffect(() => {
        if (!provider || !model) {
            return;
        }
        if (restoring.current) {
            restoring.current = false;
            // Cleared so the restore's own values are pushed if the user later
            // moves to something else, rather than being treated as already sent.
            pushed.current = "";
            return;
        }
        const key = `${provider}:${model}|${reasoningEffort ?? ""}`;
        if (pushed.current === key) {
            return;
        }
        pushed.current = key;
        void updateAgent(agentKey, {
            model,
            provider,
            reasoningEffort,
        }).catch(() => {});
    }, [provider, model, reasoningEffort, agentKey]);

    const beginRestore = useCallback(() => {
        restoring.current = true;
    }, []);

    return { beginRestore };
}

/**
 * Push the route onto the conversation currently open, which records what that
 * one conversation ran with.
 *
 * Unlike the agent writer this is never suppressed, because nothing restores a
 * route into the conversation being shown -- the restore targets a different
 * conversation, and its own record is what is being written back.
 *
 * The key includes the conversation, so switching conversations re-pushes even
 * when the model did not change. It is cleared while drafting so that a
 * conversation opened after a draft pushes for itself.
 */
export function useSessionRouteSync({
    selectedModelId,
    reasoningEffort,
    isNewChat,
    threadId,
}: {
    selectedModelId: string | null;
    reasoningEffort: string | null;
    isNewChat: boolean;
    threadId: string | null;
}): void {
    const pushed = useRef("");
    const { provider, model } = routeOf(selectedModelId);

    useEffect(() => {
        if (isNewChat || !provider || !model || !threadId) {
            pushed.current = "";
            return;
        }
        const key = `${threadId}|${provider}:${model}|${reasoningEffort ?? ""}`;
        if (pushed.current === key) {
            return;
        }
        pushed.current = key;
        void setSessionRoute(threadId, {
            provider,
            model,
            // snake_case here against camelCase above: two different endpoints,
            // and the difference is load-bearing rather than cosmetic.
            reasoning_effort: reasoningEffort,
        }).catch(() => {});
    }, [isNewChat, provider, model, reasoningEffort, threadId]);
}