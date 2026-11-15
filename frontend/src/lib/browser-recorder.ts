/** Microphone recording through the Web MediaRecorder API.
 *
 * Recording belongs to the client: a headless Linux server has no microphone,
 * so the browser (or the desktop webview) captures audio and uploads bytes.
 */

export type BrowserRecording = {
    /** Stop the recorder and resolve with the captured audio. */
    stop: () => Promise<Blob>;
    /** Stop and release the microphone without producing audio. */
    cancel: () => void;
};

const MIME_CANDIDATES = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
];

export function canRecordInBrowser(): boolean {
    return (
        typeof navigator !== "undefined" &&
        typeof navigator.mediaDevices?.getUserMedia === "function" &&
        typeof MediaRecorder !== "undefined"
    );
}

export async function startBrowserRecording(): Promise<BrowserRecording> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MIME_CANDIDATES.find((type) =>
        typeof MediaRecorder.isTypeSupported === "function"
            ? MediaRecorder.isTypeSupported(type)
            : false,
    );
    const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
    );
    const chunks: BlobPart[] = [];
    recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
            chunks.push(event.data);
        }
    };
    const stopped = new Promise<Blob>((resolve) => {
        recorder.onstop = () => {
            resolve(
                new Blob(chunks, {
                    type: recorder.mimeType || "audio/webm",
                }),
            );
        };
    });
    recorder.start();

    const release = () => {
        for (const track of stream.getTracks()) {
            track.stop();
        }
    };

    return {
        stop: async () => {
            recorder.stop();
            const blob = await stopped;
            release();
            return blob;
        },
        cancel: () => {
            try {
                recorder.stop();
            } catch {
                // Already stopped; releasing the microphone is the point.
            }
            release();
        },
    };
}
