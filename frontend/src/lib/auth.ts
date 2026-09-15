export type AuthCredentials = { username: string; password: string };

const STORAGE_KEY = "nova.auth";

let inMemoryCredentials: AuthCredentials | null = null;

const unauthorizedListeners = new Set<() => void>();

function encodeCredentials(username: string, password: string): string {
    const bytes = new TextEncoder().encode(`${username}:${password}`);
    let binary = "";
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
}

function decodeCredentials(encoded: string): AuthCredentials | null {
    try {
        const binary = atob(encoded);
        const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
        const text = new TextDecoder().decode(bytes);
        const separator = text.indexOf(":");
        if (separator < 0) {
            return null;
        }
        return {
            username: text.slice(0, separator),
            password: text.slice(separator + 1),
        };
    } catch {
        return null;
    }
}

export function getAuthCredentials(): AuthCredentials | null {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
            const decoded = decodeCredentials(stored);
            if (decoded) {
                return decoded;
            }
        }
    } catch {
        // Storage unavailable (restricted context) — fall through to memory.
    }
    return inMemoryCredentials ? { ...inMemoryCredentials } : null;
}

export function setAuthCredentials(credentials: AuthCredentials): void {
    inMemoryCredentials = { ...credentials };
    try {
        localStorage.setItem(
            STORAGE_KEY,
            encodeCredentials(credentials.username, credentials.password),
        );
    } catch {
        // Storage unavailable — in-memory fallback already set.
    }
}

export function clearAuthCredentials(): void {
    inMemoryCredentials = null;
    try {
        localStorage.removeItem(STORAGE_KEY);
    } catch {
        // Storage unavailable — nothing else to clear.
    }
}

export function getAuthHeader(): Record<string, string> {
    const credentials = getAuthCredentials();
    if (!credentials) {
        return {};
    }
    return {
        Authorization: `Basic ${encodeCredentials(credentials.username, credentials.password)}`,
    };
}

export function subscribeToUnauthorized(listener: () => void): () => void {
    unauthorizedListeners.add(listener);
    return () => {
        unauthorizedListeners.delete(listener);
    };
}

export function notifyUnauthorized(): void {
    for (const listener of unauthorizedListeners) {
        try {
            listener();
        } catch {
            // One throwing listener must not break the others.
        }
    }
}
