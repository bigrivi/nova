/** HTTP plumbing shared by the API modules: base URL, JSON, and error text.
 *
 *  Split out of `nova-api.ts` so a new endpoint group (tasks, compaction) adds a
 *  file instead of another hundred lines to the same one.
 */

export const DEFAULT_API_BASE = "http://127.0.0.1:8765";

const API_BASE = (process.env.NOVA_API_BASE_URL || DEFAULT_API_BASE).replace(
    /\/$/,
    "",
);

export type JsonResponse<T> = {
    items: T[];
};

export function buildUrl(path: string): string {
    return `${API_BASE}${path}`;
}

/** The backend's own error text, which is more useful than a status code. */
export async function parseErrorMessage(response: Response): Promise<string> {
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

/** Fetch a path and decode JSON, raising the backend's error message on failure. */
export async function request<T>(
    path: string,
    init?: RequestInit,
): Promise<T> {
    return parseJson<T>(await fetch(buildUrl(path), init));
}

/** Fetch a path and require a successful status, discarding the body. */
export async function send(path: string, init?: RequestInit): Promise<void> {
    await parseJson<unknown>(await fetch(buildUrl(path), init));
}

/** JSON request body init for the mutating endpoints. */
export function jsonInit(method: string, body: unknown): RequestInit {
    return {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    };
}
