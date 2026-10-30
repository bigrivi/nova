/** Nova backend HTTP/SSE client (ported from frontend/src/lib/nova-api.ts, without the Vite dependency) */
import {
    buildUrl,
    type JsonResponse,
    jsonInit,
    parseErrorMessage,
    request,
    send,
} from "./client.ts";
import type {
    NovaAgentCreateRequest,
    NovaAgentRecord,
    NovaAttachmentData,
    NovaCheckpoint,
    NovaMessageRecord,
    NovaModelCreateRequest,
    NovaModelRecord,
    NovaPermissionPolicy,
    NovaProjectRecord,
    NovaProviderCreateRequest,
    NovaProviderRecord,
    NovaRestoreReport,
    NovaSessionRoute,
    NovaSessionSummary,
    NovaStreamEvent,
} from "./types.ts";

export type StreamChatOptions = {
    message: string;
    /** What the client showed; defaults to `message` on the server. */
    displayText?: string | null;
    sessionId?: string | null;
    workspaceDir?: string | null;
    projectId?: string | null;
    provider?: string | null;
    model?: string | null;
    agentKey?: string | null;
    reasoningEffort?: string | null;
    /** Per-turn override of the permissions mode; unset uses the config file. */
    permissionMode?: string | null;
    attachments?: NovaAttachmentData[];
    /** Replay buffered frames after this sequence, then live-tail the turn. */
    resumeFromSequence?: number | null;
    onEvent: (event: NovaStreamEvent) => void;
};

export function sessionEventsUrl(): string {
    return buildUrl("/api/events");
}



export async function listModels(): Promise<NovaModelRecord[]> {
    const payload = await request<JsonResponse<NovaModelRecord>>("/api/models");
    return payload.items;
}

export async function listProviders(): Promise<NovaProviderRecord[]> {
    const payload = await request<JsonResponse<NovaProviderRecord>>(
        "/api/providers",
    );
    return payload.items;
}

/** The mode and rules the backend would judge a tool call by. */
export async function getPermissions(): Promise<NovaPermissionPolicy> {
    return request<NovaPermissionPolicy>("/api/permissions");
}

/** Turns of this session that changed files, newest first. */
export async function listCheckpoints(
    sessionId: string,
): Promise<NovaCheckpoint[]> {
    const payload = await request<JsonResponse<NovaCheckpoint>>(
        `/api/sessions/${sessionId}/checkpoints`,
    );
    return payload.items;
}

/** Put the files back and drop the turns from *checkpointId* on. */
export async function restoreCheckpoint(
    sessionId: string,
    checkpointId: string,
): Promise<NovaRestoreReport> {
    return request<NovaRestoreReport>(
        `/api/sessions/${sessionId}/checkpoints/${checkpointId}/restore`,
        { method: "POST" },
    );
}

export async function createProvider(
    payload: NovaProviderCreateRequest,
): Promise<NovaModelRecord[]> {
    const response = await request<JsonResponse<NovaModelRecord>>(
        "/api/config/providers",
        jsonInit("POST", payload),
    );
    return response.items;
}

export async function createModel(
    payload: NovaModelCreateRequest,
): Promise<NovaModelRecord[]> {
    const response = await request<JsonResponse<NovaModelRecord>>(
        "/api/config/models",
        jsonInit("POST", payload),
    );
    return response.items;
}

export async function updateAgent(
    key: string,
    data: { model: string; provider: string; reasoning_effort?: string | null },
): Promise<void> {
    await send(
        `/api/agents/${encodeURIComponent(key)}`,
        jsonInit("PATCH", data),
    );
}

export async function getAgent(
    key: string,
): Promise<{ key: string; name: string; model: string; provider: string; provider_name?: string; model_name?: string; reasoning_effort?: string | null } | null> {
    const res = await fetch(buildUrl(`/api/agents/${encodeURIComponent(key)}`));
    if (!res.ok) return null;
    return res.json();
}

export async function listSessions(options?: {
    workspaceDir?: string | null;
}): Promise<NovaSessionSummary[]> {
    const query = options?.workspaceDir
        ? `?workspace_dir=${encodeURIComponent(options.workspaceDir)}`
        : "";
    const payload = await request<JsonResponse<NovaSessionSummary>>(
        `/api/sessions${query}`,
    );
    return payload.items;
}

export async function resolveProject(
    path: string,
    name?: string | null,
): Promise<NovaProjectRecord | null> {
    try {
        const response = await fetch(buildUrl("/api/projects/resolve"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path, name: name ?? null }),
        });
        if (!response.ok) {
            return null;
        }
        return (await response.json()) as NovaProjectRecord;
    } catch {
        return null;
    }
}

/** The route a conversation recorded; null when it has none or is unknown. */
export async function getSessionRoute(
    sessionId: string,
): Promise<NovaSessionRoute | null> {
    try {
        const response = await fetch(
            buildUrl(`/api/sessions/${encodeURIComponent(sessionId)}/route`),
        );
        if (!response.ok) {
            return null;
        }
        return (await response.json()) as NovaSessionRoute;
    } catch {
        return null;
    }
}

export async function listAgents(): Promise<NovaAgentRecord[]> {
    const payload = await request<JsonResponse<NovaAgentRecord>>("/api/agents");
    return payload.items;
}

export async function createAgent(
    payload: NovaAgentCreateRequest,
): Promise<NovaAgentRecord> {
    return request<NovaAgentRecord>("/api/agents", jsonInit("POST", payload));
}

export async function deleteAgent(key: string): Promise<void> {
    await send(`/api/agents/${encodeURIComponent(key)}`, { method: "DELETE" });
}

/** Replace which primary agents may delegate to *key* (idempotent, server-side). */
export async function setAgentParents(
    key: string,
    parents: string[],
): Promise<void> {
    await send(
        `/api/agents/${encodeURIComponent(key)}/parents`,
        jsonInit("PUT", { parents }),
    );
}

/** Result of asking the backend to cancel a turn: true = confirmed,
 * false = answered but nothing was live, null = request itself failed. */
export type InterruptOutcome = boolean | null;

export async function interruptChat(sessionId: string): Promise<InterruptOutcome> {
    try {
        const response = await fetch(buildUrl("/api/chat/interrupt"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        });
        if (!response.ok) {
            return null;
        }
        const payload = (await response.json()) as { interrupted?: unknown };
        return payload.interrupted === true;
    } catch {
        // Never throws: callers report null instead of catching.
        return null;
    }
}

export async function approveCommand(options: {
    sessionId: string;
    requestId: string;
    approved: boolean;
    remember?: boolean;
}): Promise<void> {
    await send(
        "/api/chat/approve" +
            `?session_id=${encodeURIComponent(options.sessionId)}`,
        jsonInit("POST", {
            request_id: options.requestId,
            approved: options.approved,
            remember: options.remember ?? false,
        }),
    );
}

export async function listMessages(
    sessionId: string,
): Promise<NovaMessageRecord[]> {
    const payload = await request<JsonResponse<NovaMessageRecord>>(
        `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    );
    return payload.items;
}

export async function getSessionContext(
    sessionId: string,
): Promise<{ used: number; limit: number; percent: number; message_count: number }> {
    return request<{
        used: number;
        limit: number;
        percent: number;
        message_count: number;
    }>(`/api/sessions/${encodeURIComponent(sessionId)}/context`);
}

function emitFrame(
    frame: string,
    onEvent: (event: NovaStreamEvent) => void,
): void {
    const payload = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");

    if (!payload || payload === "[DONE]") {
        return;
    }
    onEvent(JSON.parse(payload) as NovaStreamEvent);
}

export async function streamChat(options: StreamChatOptions): Promise<void> {
    const response = await fetch(buildUrl("/api/chat/stream"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            message: options.message,
            display_text: options.displayText || undefined,
            session_id: options.sessionId || undefined,
            workspace_dir: options.workspaceDir || undefined,
            project_id: options.projectId || undefined,
            provider: options.provider || undefined,
            model: options.model || undefined,
            agent_key: options.agentKey || undefined,
            reasoning_effort: options.reasoningEffort || undefined,
            permission_mode: options.permissionMode || undefined,
            attachments: options.attachments || [],
            resume_from_seq: options.resumeFromSequence ?? undefined,
        }),
    });

    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    if (!response.body) {
        throw new Error("Stream response did not include a body.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
            const frame = buffer.slice(0, boundary).trim();
            buffer = buffer.slice(boundary + 2);
            if (frame) {
                emitFrame(frame, options.onEvent);
            }
            boundary = buffer.indexOf("\n\n");
        }

        if (done) {
            const finalFrame = buffer.trim();
            if (finalFrame) {
                emitFrame(finalFrame, options.onEvent);
            }
            return;
        }
    }
}
