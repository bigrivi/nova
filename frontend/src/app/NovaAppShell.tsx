import { AssistantRuntimeProvider } from "@assistant-ui/react";

import { LoginDialog } from "../components/auth/login-dialog";
import { TooltipProvider } from "../components/ui/tooltip";
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

    const conversations = useConversations({
        models: modelConfig.models,
        selectedModelId: modelConfig.selectedModelId,
        selectedAgentKey: agentSelection.selectedAgentKey,
        syncAgentForThread: agentSelection.syncAgentForThread,
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
        composerText: conversations.composerText,
        setThreadMessages: conversations.setThreadMessages,
        submitPrompt: conversations.submitPrompt,
        handleCancel: conversations.handleCancel,
        switchToDraftThread: conversations.switchToDraftThread,
        selectThread: conversations.selectThread,
        handleRenameThread: conversations.handleRenameThread,
        handleDeleteThread: conversations.handleDeleteThread,
    });

    const isNewChat = conversations.isDraftThread;
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
                            viewport.collapseSidebarOnNarrowViewport();
                        }}
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
                        composerText={conversations.composerText}
                        isRunning={conversations.isRunning}
                        onComposerChange={conversations.setComposerText}
                        onComposerSubmit={() => {
                            void handleComposerSubmit();
                        }}
                        onCancel={() => {
                            void conversations.handleCancel();
                        }}
                        models={modelConfig.models}
                        selectedModelId={modelConfig.selectedModelId}
                        onSelectModel={modelConfig.handleModelSelect}
                        agents={agentSelection.agents}
                        selectedAgentKey={agentSelection.selectedAgentKey}
                        onSelectAgent={agentSelection.selectAgent}
                        isNewChat={isNewChat}
                        draftProjectName={draftProjectName}
                        onRemoveProject={conversations.clearDraftProject}
                        sessionAgentKey={sessionAgentKey}
                        sessionProjectName={sessionProjectName}
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
