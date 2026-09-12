export function errorTextFromResult(result: unknown): string | null {
    if (typeof result === "string") {
        return result.trim() || null;
    }
    if (result && typeof result === "object" && !Array.isArray(result)) {
        const raw = result as Record<string, unknown>;
        const candidate = raw.content ?? raw.error ?? raw.message;
        if (typeof candidate === "string" && candidate.trim()) {
            return candidate.trim();
        }
    }
    return null;
}
