import { useEffect, useMemo, useRef, useState } from "react";

import { SettingsDialog } from "../../components/settings-dialog";
import {
    ThreadSidebar,
    type SidebarDispatch,
} from "../../components/sidebar/thread-sidebar";
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
    onDeleteThread: (
        threadId: string,
        nextThreadId: string | null,
    ) => Promise<void>;
    onAgentsChanged: (agents: NovaAgent[]) => void;
    onModelsUpdated: (models: NovaModelRecord[]) => void;
    onProvidersRefresh: () => Promise<void>;
    onConfigStatusChange: (message: string | null) => void;
    onCollapseOnNarrowViewport: () => void;
}

/**
 * The collapsible thread-list sidebar with its mobile scrim. Owns the unified
 * settings dialog opened from the sidebar, since it is the component that
 * triggers it. Renders nothing when collapsed.
 *
 * The shell rebuilds every handler on each render (once per streamed token), so
 * they are funnelled through one stable dispatch; that is what lets the session
 * list below sit untouched while the thread streams.
 */
export function NovaSidebarPanel(props: NovaSidebarPanelProps) {
    const {
        collapsed,
        threads,
        projects,
        activeThreadListId,
        isRunning,
        agents,
        models,
        providers,
    } = props;
    const [isSettingsDialogOpen, setIsSettingsDialogOpen] = useState(false);

    const latest = useRef(props);
    useEffect(() => {
        latest.current = props;
    });
    const dispatch = useMemo<SidebarDispatch>(
        () => ({
            collapseSidebar: () => latest.current.onCollapse(),
            collapseSidebarOnNarrowViewport: () =>
                latest.current.onCollapseOnNarrowViewport(),
            newThread: () => latest.current.onNewThread(),
            selectThread: (threadId) =>
                latest.current.onSelectThread(threadId),
            renameThread: (threadId, title) =>
                latest.current.onRenameThread(threadId, title),
            pinThread: (threadId, pinned) =>
                latest.current.onPinThread(threadId, pinned),
            moveThread: (threadId, projectId) =>
                latest.current.onMoveThread(threadId, projectId),
            deleteThread: (threadId, nextThreadId) =>
                latest.current.onDeleteThread(threadId, nextThreadId),
            createProject: (name, path) =>
                latest.current.onCreateProject(name, path),
            newThreadInProject: (projectId) => {
                latest.current.onNewThreadInProject(projectId);
                latest.current.onCollapseOnNarrowViewport();
            },
            renameProject: (projectId, name) =>
                latest.current.onRenameProject(projectId, name),
            deleteProject: (projectId) =>
                latest.current.onDeleteProject(projectId),
            openSettings: () => setIsSettingsDialogOpen(true),
        }),
        [],
    );

    const settingsHandlers = useMemo(
        () => ({
            onAgentsChanged: (next: NovaAgent[]) =>
                latest.current.onAgentsChanged(next),
            onModelsUpdated: (next: NovaModelRecord[]) =>
                latest.current.onModelsUpdated(next),
            onProvidersRefresh: () => latest.current.onProvidersRefresh(),
            onConfigStatusChange: (message: string | null) =>
                latest.current.onConfigStatusChange(message),
        }),
        [],
    );
    const settingsDialog = useMemo(
        () => (
            <SettingsDialog
                open={isSettingsDialogOpen}
                onOpenChange={setIsSettingsDialogOpen}
                agents={agents}
                models={models}
                providers={providers}
                {...settingsHandlers}
            />
        ),
        [isSettingsDialogOpen, agents, models, providers, settingsHandlers],
    );

    return (
        <>
            <div
                className={cn(
                    "fixed inset-0 z-40 bg-black/30 md:hidden",
                    collapsed && "hidden",
                )}
                onClick={dispatch.collapseSidebar}
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
                    dispatch={dispatch}
                />
            </div>
            {settingsDialog}
        </>
    );
}

