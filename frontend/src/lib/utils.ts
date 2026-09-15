import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

/**
 * crypto.randomUUID is only available in secure contexts (localhost/HTTPS).
 * Fall back to a local id when served over plain LAN HTTP.
 */
export function randomId(): string {
    if (
        typeof crypto !== "undefined" &&
        typeof crypto.randomUUID === "function"
    ) {
        return crypto.randomUUID();
    }
    return `id-${Date.now().toString(36)}-${Math.floor(
        Math.random() * Number.MAX_SAFE_INTEGER,
    ).toString(36)}`;
}
