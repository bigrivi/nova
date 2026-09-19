import { useState } from "react";

import { AgentsManagerDialog } from "../../components/assistant-ui/agents-manager-dialog";
import { MemoryManagerDialog } from "../../components/assistant-ui/memory-manager-dialog";
import { ModelsManagerDialog } from "../../components/assistant-ui/models-manager-dialog";
import { ThreadSidebar } from "../../components/sidebar/thread-sidebar";
import type {
    NovaAgent,
    NovaModelRecord,
    NovaProject,
    NovaProviderRecord,
    NovaThreadSummary,
} from "../../types/nova";

export interface NovaSidebarPanelProps {
    collapsed: boolean;
    threads: NovaThreadSummary[];
    projects: NovaProject[];
    activeThreadListId: string | undefined;
    isRunning: boolean;
    agents: NovaAgent[];
    models: NovaModelRecord[];
    providers: NovaProviderRecord[];
    onCollapse: () => void;
    onNewThread: () => void;
    onNewThreadInProject: (projectId: string) => void;
    onCreateProject: (
        name: string,
        path?: string | null,
    ) => Promise<NovaProject | null>;
    onRenameProject: (projectId: string, name: string) => Promise<void>;
    onDeleteProject: (projectId: string) => Promise<void>;
    onSelectThread: (threadId: string) => void;
    onRenameThread: (threadId: string, newTitle: string) => Promise<void>;
    onPinThread: (threadId: string, pinned: boolean) => Promise<void>;
    onMoveThread: (threadId: string, projectId: string | null) => Promise<void>;
    onDeleteThread: (threadId: string) => Promise<void>;
    onAgentsChanged: (agents: NovaAgent[]) => void;
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onConfigStatusChange: (message: string | null) => void;
}

/**
 * The collapsible thread-list sidebar with its mobile scrim. Owns the three
 * manager dialogs opened from the sidebar (memory, agents, models), since it
 * is the component that triggers them. Renders nothing when collapsed.
 */
export function NovaSidebarPanel({
    collapsed,
    threads,
    projects,
    activeThreadListId,
    isRunning,
    agents,
    models,
    providers,
    onCollapse,
    onNewThread,
    onNewThreadInProject,
    onCreateProject,
    onRenameProject,
    onDeleteProject,
    onSelectThread,
    onRenameThread,
    onPinThread,
    onMoveThread,
    onDeleteThread,
    onAgentsChanged,
    onModelsUpdated,
    onProvidersRefresh,
    onConfigStatusChange,
}: NovaSidebarPanelProps) {
    const [isMemoryDialogOpen, setIsMemoryDialogOpen] = useState(false);
    const [isModelsDialogOpen, setIsModelsDialogOpen] = useState(false);
    const [isAgentsDialogOpen, setIsAgentsDialogOpen] = useState(false);

    if (collapsed) {
        return null;
    }

    return (
        <>
            <div
                className="fixed inset-0 z-40 bg-black/30 md:hidden"
                onClick={onCollapse}
                aria-hidden="true"
            />
            <div className="fixed top-0 left-0 z-40 h-full shadow-2xl md:contents md:shadow-none">
                <ThreadSidebar
                    threads={threads}
                    projects={projects}
                    activeThreadId={activeThreadListId}
                    runningThreadId={isRunning ? activeThreadListId : undefined}
                    disabled={false}
                    onCollapse={onCollapse}
                    onNewThread={onNewThread}
                    onNewThreadInProject={onNewThreadInProject}
                    onCreateProject={onCreateProject}
                    onRenameProject={onRenameProject}
                    onDeleteProject={onDeleteProject}
                    onSelectThread={onSelectThread}
                    onRenameThread={onRenameThread}
                    onPinThread={onPinThread}
                    onMoveThread={onMoveThread}
                    onDeleteThread={onDeleteThread}
                    onOpenMemory={() => setIsMemoryDialogOpen(true)}
                    onOpenModels={() => setIsModelsDialogOpen(true)}
                    onOpenAgents={() => setIsAgentsDialogOpen(true)}
                />
            </div>
            <MemoryManagerDialog
                open={isMemoryDialogOpen}
                onOpenChange={setIsMemoryDialogOpen}
            />
            <AgentsManagerDialog
                open={isAgentsDialogOpen}
                onOpenChange={setIsAgentsDialogOpen}
                agents={agents}
                models={models}
                onAgentsChanged={onAgentsChanged}
            />
            <ModelsManagerDialog
                open={isModelsDialogOpen}
                onOpenChange={setIsModelsDialogOpen}
                providers={providers}
                models={models}
                onModelsUpdated={onModelsUpdated}
                onProvidersRefresh={onProvidersRefresh}
                onStatusChange={onConfigStatusChange}
            />
        </>
    );
}
