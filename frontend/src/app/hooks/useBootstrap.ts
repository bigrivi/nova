import { startTransition, useEffect, useRef, useState } from "react";

import { subscribeToUnauthorized } from "../../lib/auth";
import {
    getAgent,
    listAgents,
    listModels,
    listProjects,
    listProviders,
    listSessions,
} from "../../lib/nova-api";
import { readStoredAgentKey } from "../../lib/agent-preference";
import { DEFAULT_AGENT_KEY } from "../../lib/nova-constants";
import { toThreadSummary } from "../../lib/thread-summary";
import type {
    NovaAgent,
    NovaModelRecord,
    NovaProject,
    NovaProviderRecord,
    NovaThreadSummary,
} from "../../types/nova";

export interface BootstrapSetters {
    setModels: (models: NovaModelRecord[]) => void;
    setProviders: (providers: NovaProviderRecord[]) => void;
    setThreads: (threads: NovaThreadSummary[]) => void;
    setProjects: (projects: NovaProject[]) => void;
    setAgents: (agents: NovaAgent[]) => void;
    setSelectedModelId: (modelId: string) => void;
    setSelectedAgentKey: (agentKey: string) => void;
}

export interface BootstrapControls {
    authRequired: boolean;
    setAuthRequired: (required: boolean) => void;
    reload: () => void;
}

/**
 * Load all first-paint data in one settled batch so a single failing endpoint
 * (an older backend without /api/projects, a transient error) never blanks the
 * shell, preselect the main agent's model, and reset an unknown stored agent
 * key. Also wires the unauthorized subscription and exposes a reload used after
 * login.
 */
export function useBootstrap(setters: BootstrapSetters): BootstrapControls {
    const [authRequired, setAuthRequired] = useState(false);
    const bootstrapRef = useRef<() => void>(() => {});
    const settersRef = useRef(setters);

    useEffect(() => {
        settersRef.current = setters;
    });

    useEffect(() => {
        let cancelled = false;

        async function bootstrap() {
            try {
                const [
                    modelsResult,
                    providersResult,
                    sessionsResult,
                    projectsResult,
                    agentsResult,
                ] = await Promise.allSettled([
                    listModels(),
                    listProviders(),
                    listSessions(),
                    listProjects(),
                    listAgents(),
                ]);

                if (cancelled) {
                    return;
                }

                const availableModels =
                    modelsResult.status === "fulfilled" ? modelsResult.value : [];
                const availableProviders =
                    providersResult.status === "fulfilled"
                        ? providersResult.value
                        : [];
                const savedSessions =
                    sessionsResult.status === "fulfilled"
                        ? sessionsResult.value
                        : [];
                const savedProjects =
                    projectsResult.status === "fulfilled"
                        ? projectsResult.value
                        : [];
                const savedAgents =
                    agentsResult.status === "fulfilled"
                        ? agentsResult.value
                        : [];
                for (const result of [
                    modelsResult,
                    providersResult,
                    sessionsResult,
                    projectsResult,
                    agentsResult,
                ]) {
                    if (result.status === "rejected") {
                        console.error("Bootstrap request failed:", result.reason);
                    }
                }

                const setters = settersRef.current;

                try {
                    const agent = await getAgent("main");
                    if (agent?.provider && agent?.model) {
                        const modelId = `${agent.provider}:${agent.model}`;
                        if (availableModels.some((m) => m.id === modelId)) {
                            setters.setSelectedModelId(modelId);
                        }
                    }
                } catch {
                    // Best-effort model preselect; ignore when /api/agents/main
                    // is unavailable so the shell still boots.
                }

                const storedAgentKey = readStoredAgentKey();
                const storedAgentKnown = savedAgents.some(
                    (agent) =>
                        agent.key === storedAgentKey && agent.kind === "main",
                );

                startTransition(() => {
                    setters.setModels(availableModels);
                    setters.setProviders(availableProviders);
                    setters.setThreads(savedSessions.map(toThreadSummary));
                    setters.setProjects(savedProjects);
                    setters.setAgents(savedAgents);
                    if (!storedAgentKnown) {
                        setters.setSelectedAgentKey(DEFAULT_AGENT_KEY);
                    }
                });
            } catch (error) {
                if (!cancelled) {
                    console.error(error);
                }
            }
        }

        bootstrapRef.current = () => {
            cancelled = false;
            void bootstrap();
        };
        void bootstrap();

        return () => {
            cancelled = true;
            bootstrapRef.current = () => {};
        };
    }, []);

    useEffect(() => subscribeToUnauthorized(() => setAuthRequired(true)), []);

    return {
        authRequired,
        setAuthRequired,
        reload: () => bootstrapRef.current(),
    };
}
