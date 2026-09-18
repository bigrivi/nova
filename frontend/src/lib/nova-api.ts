import type {
    NovaAttachmentData,
    NovaDirectoryListing,
    NovaMemoryRecord,
    NovaMessageRecord,
    NovaModelCreateRequest,
    NovaModelRecord,
    NovaModelUpdateRequest,
    NovaProject,
    NovaProviderCreateRequest,
    NovaProviderRecord,
    NovaProviderUpdateRequest,
    NovaSessionSummary,
    NovaStreamEvent,
} from "../types/nova";
import { getAuthHeader, notifyUnauthorized } from "./auth";
import { parseSseFrame } from "./thread-stream";

type JsonResponse<T> = {
    items: T[];
};

type StreamChatOptions = {
    message: string;
    sessionId?: string | null;
    provider?: string | null;
    model?: string | null;
    workspaceDir?: string | null;
    projectId?: string | null;
    attachments?: NovaAttachmentData[];
    onEvent: (event: NovaStreamEvent) => void;
    signal?: AbortSignal;
    resumeFromSequence?: number | null;
    onSequence?: (sequence: number) => void;
};

export type StreamStatus = {
    status: string;
    last_seq: number;
};

const LAST_SEQUENCE_KEY_PREFIX = "nova:lastSeq:";

function lastSequenceKey(sessionId: string): string {
    return `${LAST_SEQUENCE_KEY_PREFIX}${sessionId}`;
}

function readLocalStorage(key: string): string | null {
    try {
        if (typeof localStorage === "undefined") {
            return null;
        }
        return localStorage.getItem(key);
    } catch {
        return null;
    }
}

export function getLastSequence(sessionId: string): number | null {
    const raw = readLocalStorage(lastSequenceKey(sessionId));
    if (raw == null) {
        return null;
    }
    const parsed = Number.parseInt(raw, 10);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export function setLastSequence(sessionId: string, sequence: number): void {
    try {
        if (typeof localStorage === "undefined") {
            return;
        }
        localStorage.setItem(lastSequenceKey(sessionId), String(sequence));
    } catch {
        // Storage may be unavailable (private mode, quota); streaming still works.
    }
}

export function clearLastSequence(sessionId: string): void {
    try {
        if (typeof localStorage === "undefined") {
            return;
        }
        localStorage.removeItem(lastSequenceKey(sessionId));
    } catch {
        // ignore
    }
}

export async function getStreamStatus(
    sessionId: string,
): Promise<StreamStatus> {
    const response = await apiFetch(
        `/api/chat/stream/status?session_id=${encodeURIComponent(sessionId)}`,
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    return (await response.json()) as StreamStatus;
}

export type ActiveStream = {
    session_id: string;
    status: string;
};

export async function getActiveStreams(): Promise<ActiveStream[]> {
    const response = await apiFetch(`/api/chat/stream/active`);
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    const body = (await response.json()) as { streams?: ActiveStream[] };
    return Array.isArray(body.streams) ? body.streams : [];
}

const STREAM_MAX_ATTEMPTS = 6;
const STREAM_BACKOFF_BASE_MS = 1000;
const STREAM_BACKOFF_MAX_MS = 30000;

export function streamBackoffBaseMs(attempt: number): number {
    return Math.min(
        STREAM_BACKOFF_MAX_MS,
        STREAM_BACKOFF_BASE_MS * 2 ** Math.max(0, attempt),
    );
}

function streamBackoffDelayMs(attempt: number): number {
    return streamBackoffBaseMs(attempt) * (0.8 + Math.random() * 0.4);
}

function sleepMs(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        if (signal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
        }
        const timer = setTimeout(() => {
            signal?.removeEventListener("abort", onAbort);
            resolve();
        }, ms);
        const onAbort = () => {
            clearTimeout(timer);
            reject(new DOMException("Aborted", "AbortError"));
        };
        signal?.addEventListener("abort", onAbort, { once: true });
    });
}

function isAbortError(error: unknown): boolean {
    return (
        error instanceof DOMException ||
        (error instanceof Error && error.name === "AbortError")
    );
}

const API_BASE = (import.meta.env.VITE_NOVA_API_BASE_URL || "").replace(
    /\/$/,
    "",
);

function buildUrl(path: string) {
    return `${API_BASE}${path}`;
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
    const authHeader = getAuthHeader();
    let headers: HeadersInit | undefined = init?.headers;
    if (Object.keys(authHeader).length > 0) {
        if (!headers) {
            headers = { ...authHeader };
        } else if (headers instanceof Headers) {
            headers.set("Authorization", authHeader["Authorization"] ?? "");
        } else if (Array.isArray(headers)) {
            headers = [...headers, ...Object.entries(authHeader)];
        } else {
            headers = { ...headers, ...authHeader };
        }
    }
    const response = await fetch(buildUrl(path), { ...init, headers });
    if (response.status === 401) {
        notifyUnauthorized();
    }
    return response;
}

async function parseErrorMessage(response: Response): Promise<string> {
    const raw = await response.text();
    if (!raw) {
        return `Request failed with status ${response.status}`;
    }

    try {
        const payload = JSON.parse(raw) as {
            detail?: string;
            message?: string;
        };
        return payload.detail || payload.message || raw;
    } catch {
        return raw;
    }
}

async function parseJson<T>(response: Response): Promise<T> {
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    return (await response.json()) as T;
}

export async function listModels(): Promise<NovaModelRecord[]> {
    const payload = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/models"),
    );
    return payload.items;
}

export async function probeAuth(): Promise<void> {
    await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/models"),
    );
}

export async function listProviders(): Promise<NovaProviderRecord[]> {
    const payload = await parseJson<JsonResponse<NovaProviderRecord>>(
        await apiFetch("/api/providers"),
    );
    return payload.items;
}

export async function createProvider(
    payload: NovaProviderCreateRequest,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/config/providers", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        }),
    );
    return response.items;
}

export async function createModel(
    payload: NovaModelCreateRequest,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/config/models", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        }),
    );
    return response.items;
}

export async function updateProvider(
    key: string,
    payload: NovaProviderUpdateRequest,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/config/providers/update", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ key, ...payload }),
        }),
    );
    return response.items;
}

export async function deleteProvider(key: string): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/config/providers/delete", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ key }),
        }),
    );
    return response.items;
}

export async function updateModel(
    provider: string,
    model: string,
    payload: NovaModelUpdateRequest,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/config/models/update", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ provider, model, ...payload }),
        }),
    );
    return response.items;
}

export async function deleteModel(
    provider: string,
    model: string,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await apiFetch("/api/config/models/delete", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ provider, model }),
        }),
    );
    return response.items;
}

export async function updateAgent(
    key: string,
    data: { model: string; provider: string },
): Promise<void> {
    await apiFetch(`/api/agents/${encodeURIComponent(key)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

export async function getAgent(
    key: string,
): Promise<{ model: string; provider: string } | null> {
    const response = await apiFetch(`/api/agents/${encodeURIComponent(key)}`);
    if (!response.ok) return null;
    return response.json();
}

export async function listSessions(): Promise<NovaSessionSummary[]> {
    const payload = await parseJson<JsonResponse<NovaSessionSummary>>(
        await apiFetch("/api/sessions"),
    );
    return payload.items;
}

export async function renameSession(
    sessionId: string,
    title: string,
): Promise<void> {
    const response = await apiFetch(
        `/api/sessions/${encodeURIComponent(sessionId)}`,
        {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title }),
        },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function setSessionWorkspace(
    sessionId: string,
    workspaceDir: string | null,
): Promise<void> {
    const response = await apiFetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/workspace`,
        {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workspace_dir: workspaceDir }),
        },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function setSessionPinned(
    sessionId: string,
    pinned: boolean,
): Promise<void> {
    const response = await apiFetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/pinned`,
        {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pinned }),
        },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function listDirectory(
    path?: string | null,
): Promise<NovaDirectoryListing> {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    return parseJson<NovaDirectoryListing>(
        await apiFetch(`/api/fs/list${query}`),
    );
}

export async function deleteSession(
    sessionId: string,
    deleteMemories = false,
): Promise<void> {
    const query = deleteMemories ? "?delete_memories=true" : "";
    const response = await apiFetch(
        `/api/sessions/${encodeURIComponent(sessionId)}${query}`,
        { method: "DELETE" },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function listMemories(): Promise<NovaMemoryRecord[]> {
    const payload = await parseJson<JsonResponse<NovaMemoryRecord>>(
        await apiFetch("/api/memories"),
    );
    return payload.items;
}

export async function listMemoriesBySession(
    sessionId: string,
): Promise<NovaMemoryRecord[]> {
    const payload = await parseJson<JsonResponse<NovaMemoryRecord>>(
        await apiFetch(
            `/api/memories?session_id=${encodeURIComponent(sessionId)}`,
        ),
    );
    return payload.items;
}

export async function deleteMemory(memoryId: string): Promise<void> {
    const response = await apiFetch(
        `/api/memories/${encodeURIComponent(memoryId)}`,
        { method: "DELETE" },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function approveCommand(options: {
    sessionId: string;
    requestId: string;
    approved: boolean;
    remember?: boolean;
}): Promise<void> {
    await apiFetch(
        "/api/chat/approve" +
            `?session_id=${encodeURIComponent(options.sessionId)}`,
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
}

export async function interruptChat(sessionId: string): Promise<void> {
    try {
        await apiFetch("/api/chat/interrupt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        });
    } catch {
        // ignore errors (e.g., stream already ended)
    }
}

export async function listMessages(
    sessionId: string,
): Promise<NovaMessageRecord[]> {
    const payload = await parseJson<JsonResponse<NovaMessageRecord>>(
        await apiFetch(
            `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
        ),
    );
    return payload.items;
}

function emitFrame(
    frame: string,
    onEvent: (event: NovaStreamEvent) => void,
    onSequence?: (sequence: number) => void,
) {
    const { sequence, payload } = parseSseFrame(frame);
    if (sequence != null) {
        onSequence?.(sequence);
    }
    if (!payload) {
        return;
    }

    const event = JSON.parse(payload) as NovaStreamEvent;
    if (sequence != null && event.sequence == null) {
        event.sequence = sequence;
    }
    onEvent(event);
}

async function runStreamOnce(
    options: StreamChatOptions,
    resumeFromSequence: number | null,
    trackSequence: (sequence: number) => void,
): Promise<void> {
    const response = await apiFetch("/api/chat/stream", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            message: options.message,
            session_id: options.sessionId || undefined,
            provider: options.provider || undefined,
            model: options.model || undefined,
            workspace_dir: options.workspaceDir || undefined,
            project_id: options.projectId || undefined,
            attachments: options.attachments || [],
            resume_from_seq: resumeFromSequence ?? undefined,
        }),
        signal: options.signal,
    });

    if (!response.ok) {
        const retryable =
            response.status >= 500 || response.status === 429;
        const error = new Error(await parseErrorMessage(response));
        if (!retryable) {
            (error as Error & { retryable?: boolean }).retryable = false;
        }
        throw error;
    }

    if (!response.body) {
        throw new Error("Stream response did not include a body.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
            const frame = buffer.slice(0, boundary).trim();
            buffer = buffer.slice(boundary + 2);
            if (frame) {
                emitFrame(frame, options.onEvent, trackSequence);
            }
            boundary = buffer.indexOf("\n\n");
        }

        if (done) {
            const finalFrame = buffer.trim();
            if (finalFrame) {
                emitFrame(finalFrame, options.onEvent, trackSequence);
            }
            return;
        }
    }
}

export async function streamChat(options: StreamChatOptions): Promise<void> {
    if (options.signal?.aborted) {
        throw new DOMException("Aborted", "AbortError");
    }

    let cursor = options.resumeFromSequence ?? null;
    let lastSeen: number | null = cursor;
    const trackSequence = (sequence: number) => {
        lastSeen = sequence;
        options.onSequence?.(sequence);
        if (options.sessionId) {
            setLastSequence(options.sessionId, sequence);
        }
    };

    let attempt = 0;
    for (;;) {
        try {
            await runStreamOnce(options, cursor, trackSequence);
            return;
        } catch (error) {
            if (isAbortError(error) || options.signal?.aborted) {
                throw error;
            }
            const nonRetryable =
                error instanceof Error &&
                (error as Error & { retryable?: boolean }).retryable === false;
            if (nonRetryable || attempt >= STREAM_MAX_ATTEMPTS - 1) {
                throw error;
            }
            cursor = lastSeen;
            await sleepMs(streamBackoffDelayMs(attempt), options.signal);
            attempt += 1;
        }
    }
}

export async function listProjects(): Promise<NovaProject[]> {
    const payload = await parseJson<JsonResponse<NovaProject>>(
        await apiFetch("/api/projects"),
    );
    return payload.items;
}

export async function createProject(
    name: string | null,
    path: string | null,
): Promise<NovaProject> {
    const response = await apiFetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path }),
    });
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    return (await response.json()) as NovaProject;
}

export async function resolveProject(
    path: string,
    name?: string | null,
): Promise<NovaProject> {
    const response = await apiFetch("/api/projects/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, name: name ?? null }),
    });
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    return (await response.json()) as NovaProject;
}

export async function updateProject(
    projectId: string,
    fields: { name?: string; path?: string | null },
): Promise<NovaProject> {
    const response = await apiFetch(
        `/api/projects/${encodeURIComponent(projectId)}`,
        {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(fields),
        },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    return (await response.json()) as NovaProject;
}

export async function deleteProject(projectId: string): Promise<void> {
    const response = await apiFetch(
        `/api/projects/${encodeURIComponent(projectId)}`,
        { method: "DELETE" },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function setSessionProject(
    sessionId: string,
    projectId: string | null,
): Promise<void> {
    const response = await apiFetch(
        `/api/sessions/${encodeURIComponent(sessionId)}/project`,
        {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_id: projectId }),
        },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}
