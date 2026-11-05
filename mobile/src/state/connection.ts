/** Connection settings: one Nova server at a time. */
import { create } from "zustand";

import {
    ApiError,
    configureClient,
    normalizeBaseUrl,
    probeConnection,
} from "../api/client";
import {
    clearConnection,
    loadConnection,
    saveConnection,
} from "../lib/storage";

export type ConnectionStatus =
    | "loading"
    | "disconnected"
    | "connecting"
    | "connected";

type ConnectInput = {
    baseUrl: string;
    username: string;
    password: string;
};

type ConnectionState = {
    status: ConnectionStatus;
    baseUrl: string;
    username: string;
    error: string | null;
    hydrate: () => Promise<void>;
    connect: (input: ConnectInput) => Promise<boolean>;
    disconnect: () => Promise<void>;
    setError: (error: string | null) => void;
};

export const useConnection = create<ConnectionState>((set) => ({
    status: "loading",
    baseUrl: "",
    username: "",
    error: null,

    hydrate: async () => {
        const stored = await loadConnection();
        if (!stored) {
            set({ status: "disconnected" });
            return;
        }
        try {
            const baseUrl = normalizeBaseUrl(stored.baseUrl);
            configureClient({
                baseUrl,
                username: stored.username,
                password: stored.password,
            });
            set({ baseUrl, username: stored.username });
            await probeConnection();
            set({ status: "connected", error: null });
        } catch (error) {
            set({
                status: "disconnected",
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not reach the server",
            });
        }
    },

    connect: async (input) => {
        set({ status: "connecting", error: null });
        let baseUrl: string;
        try {
            baseUrl = normalizeBaseUrl(input.baseUrl);
            configureClient({
                baseUrl,
                username: input.username,
                password: input.password,
            });
            await probeConnection();
        } catch (error) {
            set({
                status: "disconnected",
                error:
                    error instanceof ApiError && error.status === 401
                        ? "Authentication required: check the username and password"
                        : error instanceof Error
                          ? error.message
                          : "Could not reach the server",
            });
            return false;
        }

        await saveConnection({
            baseUrl,
            username: input.username,
            password: input.password,
        });
        set({
            status: "connected",
            baseUrl,
            username: input.username,
            error: null,
        });
        return true;
    },

    disconnect: async () => {
        await clearConnection();
        configureClient({ baseUrl: "", username: "", password: "" });
        set({
            status: "disconnected",
            baseUrl: "",
            username: "",
            error: null,
        });
    },

    setError: (error) => set({ error }),
}));
