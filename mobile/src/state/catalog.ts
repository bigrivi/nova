/** Server catalog: models and agents the composer can route to. */
import { create } from "zustand";

import { listAgents, listModels } from "../api/client";
import type { NovaAgent, NovaModelRecord } from "../api/types";

type CatalogState = {
    models: NovaModelRecord[];
    agents: NovaAgent[];
    loading: boolean;
    refresh: () => Promise<void>;
    reset: () => void;
};

export const useCatalog = create<CatalogState>((set) => ({
    models: [],
    agents: [],
    loading: false,

    // A failed catalog must not block the session list: both requests fall back
    // to empty, exactly as they did when this lived in the sessions store.
    refresh: async () => {
        set({ loading: true });
        const [models, agents] = await Promise.all([
            listModels().catch(() => [] as NovaModelRecord[]),
            listAgents().catch(() => [] as NovaAgent[]),
        ]);
        set({ models, agents, loading: false });
    },

    reset: () => set({ models: [], agents: [], loading: false }),
}));
