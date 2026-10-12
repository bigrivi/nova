import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { LoginDialog } from "../components/auth/login-dialog";
import { resolveModelEffort } from "../components/assistant-ui/elements/model-selector";
import { TooltipProvider } from "../components/ui/tooltip";
import { agentDisplayName } from "../lib/agent-display";
import { useReasoningEffortStore } from "../stores/reasoning-effort-store";
import { NovaMainPanel } from "./components/NovaMainPanel";
import { NovaSidebarPanel } from "./components/NovaSidebarPanel";
import { useAgentSelection } from "./hooks/useAgentSelection";
import { useBootstrap } from "./hooks/useBootstrap";
import { useConversations } from "./hooks/useConversations";
import { useModelConfig } from "./hooks/useModelConfig";
import { useNovaRuntime } from "./hooks/useNovaRuntime";
import { useProjects } from "./hooks/useProjects";
import { useStartupStatus } from "./hooks/useStartupStatus";
import {
    useAgentRouteSync,
    useSessionRouteSync,
} from "./hooks/useRouteSync";
import { useViewport } from "./hooks/useViewport";

export function NovaAppShell() {
    const viewport = useViewport();
    const modelConfig = useModelConfig();
    const agentSelection = useAgentSelection();
    // Backend version for the WorkBuddy-style sidebar badge, and the voice state
    // the microphone control follows -- including a take that outlived a reload.
    const { appVersion } = useStartupStatus();
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

    // The agent's defaults, and the record of the conversation on screen. Two
    // writers because a route lives in both, and they differ on purpose -- see
    // the hooks. `beginRestore` is what keeps a restore from echoing back out.
    const { beginRestore } = useAgentRouteSync({
        agentKey: agentSelection.selectedAgentKey,
        selectedModelId: modelConfig.selectedModelId,
        reasoningEffort: activeEffort ?? null,
    });

    const conversations = useConversations({
        models: modelConfig.models,
        selectedModelId: modelConfig.selectedModelId,
        selectedAgentKey: agentSelection.selectedAgentKey,
        syncAgentForThread: agentSelection.syncAgentForThread,
        getReasoningEffort: () => activeEffort ?? null,
        applySessionRoute: (route) => {
            // Reopening a conversation restores what it ran with, which is not
            // the user picking that route now. Without this the restore would
            // travel back through the agent writer and quietly overwrite the
            // default a new conversation starts from.
            beginRestore();
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

    const { runtime, config, handleComposerSubmit } = useNovaRuntime({
        setThreadMessages: conversations.setThreadMessages,
        submitPrompt: conversations.submitPrompt,
        handleCancel: conversations.handleCancel,
        switchToDraftThread: conversations.switchToDraftThread,
        selectThread: conversations.selectThread,
        handleRenameThread: conversations.handleRenameThread,
        handleDeleteThread: conversations.handleDeleteThread,
    });

    const isNewChat = conversations.isDraftThread;

    // Two writers, because a route lives in two places: the agent's defaults, and
    // each conversation's record. See the hooks for why they disagree.
    useSessionRouteSync({
        selectedModelId: modelConfig.selectedModelId,
        reasoningEffort: activeEffort ?? null,
        isNewChat: conversations.isDraftThread,
        threadId: conversations.currentThreadId,
    });

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
        <AssistantRuntimeProvider runtime={runtime} config={config}>
            <TooltipProvider>
                <div className="flex h-screen overflow-hidden bg-background text-foreground">
                    <NovaSidebarPanel
                        collapsed={viewport.isSidebarCollapsed}
                        projects={projects.projects}
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
