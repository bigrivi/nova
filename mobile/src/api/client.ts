/**
 * HTTP client for one Nova server.
 *
 * The base URL and Basic credentials are configured once on connect; every
 * call and both SSE streams read the same values. Native networking has no
 * browser origin, so no CORS handling is needed here.
 */
import type {
    ApprovalRequest,
    NovaAgent,
    NovaMessageRecord,
    NovaModelRecord,
    NovaProject,
    NovaSessionSummary,
    PendingPrompts,
    StreamStatus,
} from "./types";

type ClientConfig = {
    baseUrl: string;
    username: string;
    password: string;
};

let config: ClientConfig = { baseUrl: "", username: "", password: "" };

export class ApiError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
        super(message);
        this.name = "ApiError";
        this.status = status;
    }
}

export function configureClient(next: ClientConfig): void {
    config = {
        baseUrl: normalizeBaseUrl(next.baseUrl),
        username: next.username,
        password: next.password,
    };
}

export function clientConfig(): Readonly<ClientConfig> {
    return config;
}

/** `192.168.1.5:8765` and `https://host/` both become a usable origin. */
export function normalizeBaseUrl(raw: string): string {
    const trimmed = raw.trim().replace(/\/+$/, "");
    if (!trimmed) {
        throw new Error("Server URL is required");
    }
    const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)
        ? trimmed
        : `http://${trimmed}`;
    const match = withScheme.match(
        /^(https?):\/\/([^/?#]+)(\/[^?#]*)?$/i,
    );
    if (!match) {
        throw new Error("Server URL must be http(s)://host[:port][/path]");
    }
    const scheme = match[1]!.toLowerCase();
    const authority = match[2]!;
    const path = (match[3] ?? "").replace(/\/+$/, "");
    if (!authority) {
        throw new Error("Server URL is missing a host");
    }
    return `${scheme}://${authority}${path}`;
}

function base64(value: string): string {
    const bytes = new TextEncoder().encode(value);
    let binary = "";
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
}

export function authHeader(): Record<string, string> {
    if (!config.username && !config.password) {
        return {};
    }
    return {
        Authorization: `Basic ${base64(`${config.username}:${config.password}`)}`,
    };
}

export function apiUrl(path: string): string {
    return `${config.baseUrl}${path}`;
}

async function parseError(response: Response): Promise<string> {
    const raw = await response.text();
    if (!raw) {
        return `Request failed with status ${response.status}`;
    }
    try {
        const payload = JSON.parse(raw) as {
            detail?: unknown;
            message?: unknown;
        };
        const detail = payload.detail ?? payload.message;
        return typeof detail === "string" && detail.trim()
            ? detail
            : raw;
    } catch {
        return raw;
    }
}

export async function apiFetch(
    path: string,
    init: RequestInit = {},
): Promise<Response> {
    if (!config.baseUrl) {
        throw new ApiError("Not connected to a Nova server", 0);
    }
    const headers = {
        ...authHeader(),
        ...(init.headers ?? {}),
    };
    const response = await fetch(apiUrl(path), { ...init, headers });
    if (response.status === 401) {
        throw new ApiError("Authentication required", 401);
    }
    return response;
}

async function requestJson<T>(
    path: string,
    init: RequestInit = {},
): Promise<T> {
    const response = await apiFetch(path, init);
    if (!response.ok) {
        throw new ApiError(await parseError(response), response.status);
    }
    return (await response.json()) as T;
}

export async function probeConnection(): Promise<void> {
    const response = await fetch(apiUrl("/health"));
    if (!response.ok) {
        throw new ApiError(
            `Nova did not answer /health (${response.status})`,
            response.status,
        );
    }
    // /health is public; /api/models proves the credentials too.
    await requestJson<{ items: NovaModelRecord[] }>("/api/models");
}

export async function listSessions(): Promise<NovaSessionSummary[]> {
    const payload = await requestJson<{ items: NovaSessionSummary[] }>(
        "/api/sessions",
    );
    return payload.items;
}

export async function listProjects(): Promise<NovaProject[]> {
    const payload = await requestJson<{ items: NovaProject[] }>("/api/projects");
    return payload.items;
}

export async function createProject(
    name: string,
    path?: string | null,
): Promise<NovaProject> {
    return requestJson<NovaProject>("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path: path?.trim() || null }),
    });
}

export async function updateProject(
    projectId: string,
    fields: { name?: string; path?: string | null },
): Promise<NovaProject> {
    return requestJson<NovaProject>(
        `/api/projects/${encodeURIComponent(projectId)}`,
        {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(fields),
        },
    );
}

export async function deleteProject(projectId: string): Promise<void> {
    await requestJson(`/api/projects/${encodeURIComponent(projectId)}`, {
        method: "DELETE",
    });
}

export async function setSessionProject(
    sessionId: string,
    projectId: string | null,
): Promise<void> {
    await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}/project`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId }),
    });
}

export async function listMessages(
    sessionId: string,
): Promise<NovaMessageRecord[]> {
    const payload = await requestJson<{ items: NovaMessageRecord[] }>(
        `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    );
    return payload.items;
}

export async function listModels(): Promise<NovaModelRecord[]> {
    const payload = await requestJson<{ items: NovaModelRecord[] }>(
        "/api/models",
    );
    return payload.items;
}

export async function listAgents(): Promise<NovaAgent[]> {
    const payload = await requestJson<{ items: NovaAgent[] }>("/api/agents");
    return payload.items;
}

export async function getStreamStatus(
    sessionId: string,
): Promise<StreamStatus | null> {
    try {
        return await requestJson<StreamStatus>(
            `/api/chat/stream/status?session_id=${encodeURIComponent(sessionId)}`,
        );
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            return null;
        }
        throw error;
    }
}

export async function getSessionPending(
    sessionId: string,
): Promise<PendingPrompts> {
    return requestJson<PendingPrompts>(
        `/api/sessions/${encodeURIComponent(sessionId)}/pending`,
    );
}

export async function approveCommand(options: {
    sessionId: string;
    requestId: string;
    approved: boolean;
    remember?: boolean;
}): Promise<boolean> {
    const response = await apiFetch(
        `/api/chat/approve?session_id=${encodeURIComponent(options.sessionId)}`,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                request_id: options.requestId,
                approved: options.approved,
                remember: options.remember ?? false,
            }),
        },
    );
    return response.ok;
}

export async function cancelBackgroundTask(
    taskId: string,
    sessionId: string,
): Promise<void> {
    await requestJson(
        `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        },
    );
}

export async function interruptChat(sessionId: string): Promise<boolean> {
    try {
        const payload = await requestJson<{ interrupted: boolean }>(
            "/api/chat/interrupt",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sessionId }),
            },
        );
        return payload.interrupted === true;
    } catch {
        return false;
    }
}

export type SpeechStatus = {
    enabled: boolean;
    reason?: string | null;
};

export async function getSpeechStatus(): Promise<SpeechStatus> {
    try {
        const payload = await requestJson<SpeechStatus>("/api/speech/status");
        return { enabled: payload.enabled === true, reason: payload.reason };
    } catch {
        return { enabled: false };
    }
}

export type SessionRoute = {
    provider: string | null;
    model: string | null;
    reasoning_effort: string | null;
};

export async function getSessionRoute(
    sessionId: string,
): Promise<SessionRoute> {
    const payload = await requestJson<{
        provider?: string | null;
        model?: string | null;
        reasoning_effort?: string | null;
    }>(`/api/sessions/${encodeURIComponent(sessionId)}/route`);
    return {
        provider: payload.provider ?? null,
        model: payload.model ?? null,
        reasoning_effort: payload.reasoning_effort ?? null,
    };
}

export async function setSessionRoute(
    sessionId: string,
    route: { provider: string; model: string; reasoning_effort?: string | null },
): Promise<void> {
    await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}/route`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(route),
    });
}

export async function setSessionPinned(
    sessionId: string,
    pinned: boolean,
): Promise<void> {
    await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}/pinned`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pinned }),
    });
}

export async function renameSession(
    sessionId: string,
    title: string,
): Promise<void> {
    await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
}

export async function deleteSession(sessionId: string): Promise<void> {
    await requestJson(`/api/sessions/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
    });
}

export type { ApprovalRequest };
