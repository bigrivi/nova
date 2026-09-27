import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useEffect, useRef } from "react";

import { LoginDialog } from "../components/auth/login-dialog";
import { resolveModelEffort } from "../components/assistant-ui/elements/model-selector";
import { TooltipProvider } from "../components/ui/tooltip";
import { agentDisplayName } from "../lib/agent-display";
import { setSessionRoute } from "../lib/nova-api";
import { useReasoningEffortStore } from "../stores/reasoning-effort-store";
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

    const conversations = useConversations({
        models: modelConfig.models,
        selectedModelId: modelConfig.selectedModelId,
        selectedAgentKey: agentSelection.selectedAgentKey,
        syncAgentForThread: agentSelection.syncAgentForThread,
        getReasoningEffort: () => activeEffort ?? null,
        applySessionRoute: (route) => {
            if (route.model) {
                const match = modelConfig.models.find(
                    (model) => model.model === route.model,
                );
                if (match && match.id !== modelConfig.selectedModelId) {
                    modelConfig.handleModelSelect(match.id);
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

    // One writer for the session's route. A model change has to land on both
    // the session and the agent: the session so reopening it restores that
    // model, the agent so a brand-new chat starts from it. The effort rides
    // along in the same request because it is only meaningful for the model
    // beside it. Drafts have no session row yet - their route is recorded by
    // the backend on the first turn instead.
    const pushedRoute = useRef("");
    useEffect(() => {
        if (isNewChat || !modelConfig.selectedModelId) {
            pushedRoute.current = "";
            return;
        }
        const [provider, model] = modelConfig.selectedModelId.split(":");
        if (!provider || !model) {
            return;
        }
        const key = `${conversations.currentThreadId}|${provider}:${model}|${
            activeEffort ?? ""
        }`;
        if (pushedRoute.current === key) {
            return;
        }
        pushedRoute.current = key;
        void setSessionRoute(conversations.currentThreadId, {
            provider,
            model,
            reasoning_effort: activeEffort ?? null,
        }).catch(() => {});
    }, [
        isNewChat,
        modelConfig.selectedModelId,
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
