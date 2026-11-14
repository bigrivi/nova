/** Play a TTS reply using the backend /api/tts/synthesize endpoint. */
import { createAudioPlayer } from "expo-audio";
import { File, Paths } from "expo-file-system";

import { apiUrl, authHeader } from "../api/client";

let activePlayer: ReturnType<typeof createAudioPlayer> | null = null;

export async function speakText(text: string): Promise<void> {
    const t0 = Date.now();
    const response = await fetch(apiUrl("/api/tts/synthesize"), {
        method: "POST",
        headers: {
            ...authHeader(),
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ text }),
    });
    if (!response.ok) {
        throw new Error(`TTS failed (${response.status})`);
    }
    const buffer = await response.arrayBuffer();
    console.log("TTS fetch ms:", Date.now() - t0, "bytes:", buffer.byteLength);
    const bytes = new Uint8Array(buffer);

    const file = new File(Paths.cache, `tts-${Date.now()}.m4a`);
    await file.write(bytes);
    console.log("TTS write ms:", Date.now() - t0);

    activePlayer?.remove();
    activePlayer?.remove();
    const player = createAudioPlayer(file.uri);
    activePlayer = player;
    await new Promise<void>((resolve, reject) => {
        let finished = false;
        const finish = () => {
            if (finished) return;
            finished = true;
            clearInterval(timer);
            sub.remove();
            resolve();
        };
        const sub = player.addListener("playbackStatusUpdate", (status: any) => {
            if (status?.didJustFinish) {
                finish();
            }
            if (status?.error) {
                finished = true;
                clearInterval(timer);
                sub.remove();
                reject(new Error(String(status.error)));
            }
        });
        // Fallback poll: some Android builds do not deliver a final status event.
        const started = Date.now();
        const timer = setInterval(() => {
            const duration = player.duration || 0;
            const pos = player.currentTime || 0;
            if (duration > 0 && pos >= Math.max(0, duration - 0.2)) {
                finish();
                return;
            }
            if (!player.playing && Date.now() - started > 3000 && pos === 0) {
                finish();
            }
            if (Date.now() - started > 120000) {
                finish();
            }
        }, 200);
        player.play();
    });
    player.remove();
    if (activePlayer === player) {
        activePlayer = null;
    }
    try {
        file.delete();
    } catch {
        // best effort
    }
}
