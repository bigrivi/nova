import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useEffect, useRef, useState } from "react";

import { LoginDialog } from "../components/auth/login-dialog";
import { resolveModelEffort } from "../components/assistant-ui/elements/model-selector";
import { TooltipProvider } from "../components/ui/tooltip";
import { agentDisplayName } from "../lib/agent-display";
import { fetchAppVersion, getSpeechStatus, setSessionRoute, updateAgent } from "../lib/nova-api";
import { useReasoningEffortStore } from "../stores/reasoning-effort-store";
import { useSpeechStore } from "../stores/speech-store";
import { NovaMainPanel } from "./components/NovaMainPanel";
import { NovaSidebarPanel } from "./components/NovaSidebarPanel";
import { useAgentSelection } from "./hooks/useAgentSelection";
import { useBootstrap } from "./hooks/useBootstrap";
import { useConversations } from "./hooks/useConversations";
import { useModelConfig } from "./hooks/useModelConfig";
import { useNovaRuntime } from "./hooks/useNovaRuntime";
import { useProjects } from "./hooks/useProjects";
import { useViewport } from "./hooks/useViewport";

export function NovaAppShell() {
    const viewport = useViewport();
    const modelConfig = useModelConfig();
    const agentSelection = useAgentSelection();
    // Backend version for the WorkBuddy-style sidebar badge.
    const [appVersion, setAppVersion] = useState<string | null>(null);
    useEffect(() => {
        let live = true;
        fetchAppVersion()
            .then((version) => {
                if (live) setAppVersion(version);
            })
            .catch(() => {});
        // Microphone button visibility follows the transcription config.
        getSpeechStatus()
            .then((status) => {
                if (!live) {
                    return;
                }
                const speech = useSpeechStore.getState();
                speech.setEnabled(status.enabled);
                // A take started before a reload outlives the view; adopt it
                // so the panel offers cancel/send instead of a 409, with the
                // clock picked up where the backend left it.
                if (status.recording) {
                    const startedAt =
                        status.recording_since_ms ?? Date.now();
                    speech.setPhase("recording", startedAt);
                }
            })
            .catch(() => {});
        return () => {
            live = false;
        };
    }, []);
    const reasoningEffort = useReasoningEffortStore((state) => state.effort);
    const setReasoningEffort = useReasoningEffortStore(
        (state) => state.setEffort,
    );
    // Resolved against the selected model rather than stored pre-filtered, so
    // switching models and back keeps the level picked for the returning model.
    const activeEffort = resolveModelEffort(
        modelConfig.modelOptions,
        modelConfig.selectedModelId ?? undefined,
        reasoningEffort ?? undefined,
    );

    // Reopening a conversation restores what it ran with, which is not the
    // same as the user picking that route now. Without this the restore would
    // travel back through the writers below and quietly overwrite the default a
    // new conversation starts from.
    const restoringRoute = useRef(false);

    const conversations = useConversations({
        models: modelConfig.models,
        selectedModelId: modelConfig.selectedModelId,
        selectedAgentKey: agentSelection.selectedAgentKey,
        syncAgentForThread: agentSelection.syncAgentForThread,
        getReasoningEffort: () => activeEffort ?? null,
        applySessionRoute: (route) => {
            restoringRoute.current = true;
            if (route.model) {
                const match = modelConfig.models.find(
                    (model) => model.model === route.model,
                );
                if (match && match.id !== modelConfig.selectedModelId) {
                    modelConfig.setSelectedModelId(match.id);
                }
            }
            if (route.reasoning_effort !== undefined) {
                setReasoningEffort(route.reasoning_effort);
            }
        },
    });

    const projects = useProjects(conversations.setThreads);

    const bootstrap = useBootstrap({
        setModels: modelConfig.setModels,
        setProviders: modelConfig.setProviders,
        setThreads: conversations.setThreads,
        setProjects: projects.setProjects,
        setAgents: agentSelection.setAgents,
        setSelectedModelId: modelConfig.setSelectedModelId,
        setReasoningEffort,
        setSelectedAgentKey: agentSelection.setSelectedAgentKey,
    });

    const { runtime, aui, handleComposerSubmit } = useNovaRuntime({
        currentMessages: conversations.currentMessages,
        isRunning: conversations.isRunning,
        currentThreadId: conversations.currentThreadId,
        threads: conversations.threads,
        activeThreadListId: conversations.activeThreadListId,
        setThreadMessages: conversations.setThreadMessages,
        submitPrompt: conversations.submitPrompt,
        handleCancel: conversations.handleCancel,
        switchToDraftThread: conversations.switchToDraftThread,
        selectThread: conversations.selectThread,
        handleRenameThread: conversations.handleRenameThread,
        handleDeleteThread: conversations.handleDeleteThread,
    });

    const isNewChat = conversations.isDraftThread;

    // Two writers, because a route lives in two places.
    //
    // The agent row is the default a brand-new conversation starts from, so it
    // takes every explicit pick - including one made while composing a draft,
    // which is the case that used to be lost. The session row is what that one
    // conversation ran with, so reopening it restores those values. The level
    // rides along with the model in both, since it means nothing beside a
    // different model.
    const selectedModel = modelConfig.selectedModelId;
    const routeParts = selectedModel ? selectedModel.split(":") : [];
    const routeProvider = routeParts[0] ?? null;
    const routeModel = routeParts[1] ?? null;

    const pushedAgent = useRef("");
    useEffect(() => {
        if (!routeProvider || !routeModel) {
            return;
        }
        if (restoringRoute.current) {
            // Consumed by this one skip: the next real change is a real change.
            restoringRoute.current = false;
            pushedAgent.current = "";
            return;
        }
        const key = `${routeProvider}:${routeModel}|${activeEffort ?? ""}`;
        if (pushedAgent.current === key) {
            return;
        }
        pushedAgent.current = key;
        void updateAgent(agentSelection.selectedAgentKey, {
            model: routeModel,
            provider: routeProvider,
            reasoningEffort: activeEffort ?? null,
        }).catch(() => {});
    }, [
        routeProvider,
        routeModel,
        activeEffort,
        agentSelection.selectedAgentKey,
    ]);

    const pushedSession = useRef("");
    useEffect(() => {
        if (isNewChat || !routeProvider || !routeModel) {
            pushedSession.current = "";
            return;
        }
        const key = `${conversations.currentThreadId}|${routeProvider}:${routeModel}|${
            activeEffort ?? ""
        }`;
        if (pushedSession.current === key) {
            return;
        }
        pushedSession.current = key;
        void setSessionRoute(conversations.currentThreadId, {
            provider: routeProvider,
            model: routeModel,
            reasoning_effort: activeEffort ?? null,
        }).catch(() => {});
    }, [
        isNewChat,
        routeProvider,
        routeModel,
        conversations.currentThreadId,
        activeEffort,
    ]);
    const activeThread = conversations.threads.find(
        (thread) => thread.id === conversations.currentThreadId,
    );
    const draftProjectName = isNewChat
        ? (projects.projects.find(
              (project) => project.id === conversations.draftProjectId,
          )?.name ?? null)
        : null;
    const sessionAgentKey = isNewChat
        ? null
        : (activeThread?.agent_key ?? null);
    const sessionProjectName = isNewChat
        ? null
        : (projects.projects.find(
              (project) => project.id === activeThread?.project_id,
          )?.name ?? null);
    const assistantAgentKey = isNewChat
        ? agentSelection.selectedAgentKey
        : sessionAgentKey;
    const assistantName = agentDisplayName(
        agentSelection.agents,
        assistantAgentKey,
    );

    return (
        <AssistantRuntimeProvider aui={aui} runtime={runtime}>
            <TooltipProvider>
                <div className="flex h-screen overflow-hidden bg-background text-foreground">
                    <NovaSidebarPanel
                        collapsed={viewport.isSidebarCollapsed}
                        threads={conversations.threads}
                        projects={projects.projects}
                        activeThreadListId={conversations.activeThreadListId}
                        isRunning={conversations.isRunning}
                        agents={agentSelection.agents}
                        models={modelConfig.models}
                        providers={modelConfig.providers}
                        appVersion={appVersion}
                        onCollapse={() => viewport.setIsSidebarCollapsed(true)}
                        onNewThread={() => {
                            conversations.switchToDraftThread();
                            viewport.collapseSidebarOnNarrowViewport();
                        }}
                        onNewThreadInProject={(projectId) => {
                            conversations.handleNewThreadInProject(projectId);
                        }}
                        onCollapseOnNarrowViewport={() =>
                            viewport.collapseSidebarOnNarrowViewport()
                        }
                        onCreateProject={projects.handleCreateProject}
                        onRenameProject={projects.handleRenameProject}
                        onDeleteProject={projects.handleDeleteProject}
                        onSelectThread={(threadId) => {
                            conversations.selectThread(threadId);
                            viewport.collapseSidebarOnNarrowViewport();
                        }}
                        onRenameThread={conversations.handleRenameThread}
                        onPinThread={conversations.handlePinThread}
                        onMoveThread={projects.handleMoveThread}
                        onDeleteThread={conversations.handleDeleteThread}
                        onAgentsChanged={agentSelection.handleAgentsChanged}
                        onModelsUpdated={
                            modelConfig.handleConfigModelsUpdated
                        }
                        onProvidersRefresh={modelConfig.refreshProviders}
                        onConfigStatusChange={modelConfig.handleConfigStatus}
                    />

                    <NovaMainPanel
                        sidebarCollapsed={viewport.isSidebarCollapsed}
                        onExpandSidebar={() =>
                            viewport.setIsSidebarCollapsed(false)
                        }
                        composerRef={conversations.composerRef}
                        isRunning={conversations.isRunning}
                        onComposerSubmit={() => {
                            void handleComposerSubmit();
                        }}
                        onCancel={() => {
                            void conversations.handleCancel();
                        }}
                        models={modelConfig.models}
                        modelOptions={modelConfig.modelOptions}
                        selectedModelId={modelConfig.selectedModelId}
                        onSelectModel={modelConfig.handleModelSelect}
                        reasoningEffort={activeEffort ?? null}
                        onReasoningEffortChange={setReasoningEffort}
                        agents={agentSelection.agents}
                        selectedAgentKey={agentSelection.selectedAgentKey}
                        onSelectAgent={agentSelection.selectAgent}
                        isNewChat={isNewChat}
                        draftProjectName={draftProjectName}
                        onRemoveProject={conversations.clearDraftProject}
                        sessionAgentKey={sessionAgentKey}
                        sessionProjectName={sessionProjectName}
                        assistantName={assistantName}
                        assistantAgentKey={assistantAgentKey}
                        threadTitle={activeThread?.title ?? null}
                        currentThreadId={conversations.currentThreadId}
                    />
                </div>

                <LoginDialog
                    open={bootstrap.authRequired}
                    onAuthenticated={() => {
                        bootstrap.setAuthRequired(false);
                        bootstrap.reload();
                    }}
                />
            </TooltipProvider>
        </AssistantRuntimeProvider>
    );
}
