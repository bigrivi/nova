/** Route chosen for new conversations: model and agent. */
import { create } from "zustand";

type RouteState = {
    modelId: string | null;
    agentKey: string | null;
    projectId: string | null;
    reasoningEffort: string | null;
    setModelId: (modelId: string | null) => void;
    setAgentKey: (agentKey: string | null) => void;
    setProjectId: (projectId: string | null) => void;
    setReasoningEffort: (effort: string | null) => void;
    reset: () => void;
};

export const useRoute = create<RouteState>((set) => ({
    modelId: null,
    agentKey: null,
    projectId: null,
    reasoningEffort: null,
    setModelId: (modelId) => set({ modelId }),
    setAgentKey: (agentKey) => set({ agentKey }),
    setProjectId: (projectId) => set({ projectId }),
    setReasoningEffort: (effort) => set({ reasoningEffort: effort }),
    reset: () =>
        set({
            modelId: null,
            agentKey: null,
            projectId: null,
            reasoningEffort: null,
        }),
}));
