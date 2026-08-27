/** Nova backend HTTP/SSE client (ported from frontend/src/lib/nova-api.ts, without the Vite dependency) */
import type {
    NovaAgentCreateRequest,
    NovaAgentRecord,
    NovaAttachmentData,
    NovaMessageRecord,
    NovaModelCreateRequest,
    NovaModelRecord,
    NovaProviderCreateRequest,
    NovaProviderRecord,
    NovaSessionSummary,
    NovaStreamEvent,
} from "./types.ts";

type JsonResponse<T> = {
    items: T[];
};

export type StreamChatOptions = {
    message: string;
    sessionId?: string | null;
    provider?: string | null;
    model?: string | null;
    attachments?: NovaAttachmentData[];
    onEvent: (event: NovaStreamEvent) => void;
};

export const DEFAULT_API_BASE = "http://127.0.0.1:8765";

const API_BASE = (process.env.NOVA_API_BASE_URL || DEFAULT_API_BASE).replace(
    /\/$/,
    "",
);

function buildUrl(path: string): string {
    return `${API_BASE}${path}`;
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
        await fetch(buildUrl("/api/models")),
    );
    return payload.items;
}

export async function listProviders(): Promise<NovaProviderRecord[]> {
    const payload = await parseJson<JsonResponse<NovaProviderRecord>>(
        await fetch(buildUrl("/api/providers")),
    );
    return payload.items;
}

export async function createProvider(
    payload: NovaProviderCreateRequest,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await fetch(buildUrl("/api/config/providers"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        }),
    );
    return response.items;
}

export async function createModel(
    payload: NovaModelCreateRequest,
): Promise<NovaModelRecord[]> {
    const response = await parseJson<JsonResponse<NovaModelRecord>>(
        await fetch(buildUrl("/api/config/models"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        }),
    );
    return response.items;
}

export async function updateAgent(
    key: string,
    data: { model: string; provider: string },
): Promise<void> {
    await fetch(buildUrl(`/api/agents/${encodeURIComponent(key)}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
}

export async function getAgent(
    key: string,
): Promise<{ model: string; provider: string } | null> {
    const res = await fetch(buildUrl(`/api/agents/${encodeURIComponent(key)}`));
    if (!res.ok) return null;
    return res.json();
}

export async function listSessions(): Promise<NovaSessionSummary[]> {
    const payload = await parseJson<JsonResponse<NovaSessionSummary>>(
        await fetch(buildUrl("/api/sessions")),
    );
    return payload.items;
}

export async function listAgents(): Promise<NovaAgentRecord[]> {
    const payload = await parseJson<JsonResponse<NovaAgentRecord>>(
        await fetch(buildUrl("/api/agents")),
    );
    return payload.items;
}

export async function createAgent(
    payload: NovaAgentCreateRequest,
): Promise<NovaAgentRecord> {
    const response = await fetch(buildUrl("/api/agents"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
    return response.json();
}

export async function deleteAgent(key: string): Promise<void> {
    const response = await fetch(
        buildUrl(`/api/agents/${encodeURIComponent(key)}`),
        {
            method: "DELETE",
        },
    );
    if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
    }
}

export async function interruptChat(sessionId: string): Promise<void> {
    try {
        await fetch(buildUrl("/api/chat/interrupt"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId }),
        });
    } catch {
        // ignore errors (e.g., stream already ended)
    }
}

export async function approveCommand(options: {
    sessionId: string;
    requestId: string;
    approved: boolean;
    remember?: boolean;
}): Promise<void> {
    await fetch(
        buildUrl("/api/chat/approve") +
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

export async function listMessages(
    sessionId: string,
): Promise<NovaMessageRecord[]> {
    const payload = await parseJson<JsonResponse<NovaMessageRecord>>(
        await fetch(
            buildUrl(`/api/sessions/${encodeURIComponent(sessionId)}/messages`),
        ),
    );
    return payload.items;
}

export async function getSessionContext(
    sessionId: string,
): Promise<{ used: number; limit: number; percent: number; message_count: number }> {
    return parseJson<{ used: number; limit: number; percent: number; message_count: number }>(
        await fetch(buildUrl(`/api/sessions/${encodeURIComponent(sessionId)}/context`)),
    );
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
            session_id: options.sessionId || undefined,
            provider: options.provider || undefined,
            model: options.model || undefined,
            attachments: options.attachments || [],
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
