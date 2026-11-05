/** Upload a device recording to the server's transcription route. */
import { File, UploadType } from "expo-file-system";

import { apiUrl, authHeader } from "../api/client";

function detail(body: string, status: number): string {
    try {
        const payload = JSON.parse(body) as { detail?: unknown };
        if (typeof payload.detail === "string" && payload.detail.trim()) {
            return payload.detail;
        }
    } catch {
        // Not JSON; use the status line.
    }
    return `Transcription failed (${status})`;
}

export async function transcribeAudio(uri: string): Promise<string> {
    const suffix = uri.split("?")[0]?.match(/\.[a-z0-9]+$/i)?.[0] ?? ".m4a";
    const file = new File(uri);
    const result = await file.upload(
        `${apiUrl("/api/speech/transcribe")}?suffix=${encodeURIComponent(suffix)}`,
        {
            httpMethod: "POST",
            uploadType: UploadType.BINARY_CONTENT,
            mimeType: "audio/m4a",
            headers: {
                ...authHeader(),
                "Content-Type": "audio/m4a",
            },
        },
    );
    if (result.status < 200 || result.status >= 300) {
        throw new Error(detail(result.body, result.status));
    }
    const payload = JSON.parse(result.body) as { text?: unknown };
    return typeof payload.text === "string" ? payload.text : "";
}
