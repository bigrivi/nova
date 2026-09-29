import { create } from "zustand";

export type SpeechPhase = "idle" | "recording" | "transcribing";

type SpeechStore = {
    /** Backend reports a configured provider and a supported platform. */
    enabled: boolean;
    setEnabled: (enabled: boolean) => void;
    phase: SpeechPhase;
    /** Epoch ms of the current take, for the elapsed-time readout. */
    startedAt: number | null;
    setPhase: (phase: SpeechPhase, startedAt?: number | null) => void;
    /** Last failure, shown once as a composer hint. */
    error: string | null;
    setError: (error: string | null) => void;
};

/**
 * Voice-input UI state. Recording itself lives in the backend (native
 * OS audio API); this store only tracks capability and phase so the mic
 * control renders consistently across remounts.
 */
export const useSpeechStore = create<SpeechStore>()((set) => ({
    enabled: false,
    setEnabled: (enabled) => set({ enabled }),
    phase: "idle",
    startedAt: null,
    setPhase: (phase, startedAt = null) => set({ phase, startedAt }),
    error: null,
    setError: (error) => set({ error }),
}));
