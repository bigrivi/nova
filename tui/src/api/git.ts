/** Read-only git queries for the current session's workspace. */
import { jsonInit, request } from "./client.ts";
import type {
    NovaCommitPlan,
    NovaCommitResult,
    NovaGitDiff,
    NovaGitStatus,
    NovaReviewResult,
} from "./types.ts";

/** Branch, upstream distance and changed files. */
export async function gitStatus(sessionId: string): Promise<NovaGitStatus> {
    return request<NovaGitStatus>(
        `/api/git/status?session_id=${encodeURIComponent(sessionId)}`,
    );
}

/** Unified diff against HEAD, already truncated by the backend when huge. */
export async function gitDiff(
    sessionId: string,
    path?: string | null,
): Promise<NovaGitDiff> {
    const params = new URLSearchParams({ session_id: sessionId });
    if (path) params.set("path", path);
    return request<NovaGitDiff>(`/api/git/diff?${params.toString()}`);
}

/** Files this session changed plus a proposed message. Stages nothing. */
export async function planCommit(sessionId: string): Promise<NovaCommitPlan> {
    return request<NovaCommitPlan>(
        `/api/git/commit-plan?session_id=${encodeURIComponent(sessionId)}`,
    );
}

/** Stage exactly these paths and commit them. */
export async function commitChanges(
    sessionId: string,
    message: string,
    paths: string[],
): Promise<NovaCommitResult> {
    return request<NovaCommitResult>(
        "/api/git/commit",
        jsonInit("POST", { session_id: sessionId, message, paths }),
    );
}

/** One model pass over the uncommitted diff. */
export async function reviewChanges(
    sessionId: string,
): Promise<NovaReviewResult> {
    return request<NovaReviewResult>(
        "/api/git/review",
        jsonInit("POST", { session_id: sessionId }),
    );
}
