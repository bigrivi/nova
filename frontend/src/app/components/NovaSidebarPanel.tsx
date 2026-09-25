import { useState } from "react";

import { SettingsDialog } from "../../components/settings-dialog";
import { ThreadSidebar } from "../../components/sidebar/thread-sidebar";
import { cn } from "../../lib/utils";
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
 * The collapsible thread-list sidebar with its mobile scrim. Owns the unified
 * settings dialog opened from the sidebar, since it is the component that
 * triggers it. Renders nothing when collapsed.
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
    const [isSettingsDialogOpen, setIsSettingsDialogOpen] = useState(false);

    return (
        <>
            <div
                className={cn(
                    "fixed inset-0 z-40 bg-black/30 md:hidden",
                    collapsed && "hidden",
                )}
                onClick={onCollapse}
                aria-hidden="true"
            />
            {/* Below md the sidebar is a fixed drawer; from md up it drops the
                wrapper box and joins the shell's flex row, so the breakpoint
                alone decides between overlay and docked layout. */}
            <div
                className={cn(
                    "top-0 left-0 z-40 h-full",
                    collapsed
                        ? "hidden"
                        : "fixed shadow-2xl md:contents md:shadow-none",
                )}
            >
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
                    onOpenSettings={() => setIsSettingsDialogOpen(true)}
                />
            </div>
            <SettingsDialog
                open={isSettingsDialogOpen}
                onOpenChange={setIsSettingsDialogOpen}
                agents={agents}
                models={models}
                providers={providers}
                onAgentsChanged={onAgentsChanged}
                onModelsUpdated={onModelsUpdated}
                onProvidersRefresh={onProvidersRefresh}
                onConfigStatusChange={onConfigStatusChange}
            />
        </>
    );
}
