import { useState } from "react";

import { DRAFT_THREAD_ID } from "../../lib/nova-constants";
import {
    createProject,
    deleteProject,
    setSessionProject,
    updateProject,
} from "../../lib/nova-api";
import type { NovaProject, NovaThreadSummary } from "../../types/nova";

export interface ProjectControls {
    projects: NovaProject[];
    setProjects: React.Dispatch<React.SetStateAction<NovaProject[]>>;
    handleCreateProject: (
        name: string,
        path?: string | null,
    ) => Promise<NovaProject | null>;
    handleRenameProject: (projectId: string, name: string) => Promise<void>;
    handleDeleteProject: (projectId: string) => Promise<void>;
    handleMoveThread: (
        threadId: string,
        projectId: string | null,
    ) => Promise<void>;
}

/**
 * Own the project list and its CRUD operations. Deleting a project and moving
 * a thread also reconcile the thread list via the injected setter, keeping the
 * project_id on affected threads consistent.
 */
export function useProjects(
    setThreads: React.Dispatch<React.SetStateAction<NovaThreadSummary[]>>,
): ProjectControls {
    const [projects, setProjects] = useState<NovaProject[]>([]);

    async function handleCreateProject(
        name: string,
        path: string | null = null,
    ): Promise<NovaProject | null> {
        try {
            const project = await createProject(name, path);
            setProjects((previous) => [project, ...previous]);
            return project;
        } catch (error) {
            console.error("Failed to create project:", error);
            return null;
        }
    }

    async function handleRenameProject(projectId: string, name: string) {
        try {
            const project = await updateProject(projectId, { name });
            setProjects((previous) =>
                previous.map((item) => (item.id === projectId ? project : item)),
            );
        } catch (error) {
            console.error("Failed to rename project:", projectId, error);
        }
    }

    async function handleDeleteProject(projectId: string) {
        try {
            await deleteProject(projectId);
            setProjects((previous) =>
                previous.filter((item) => item.id !== projectId),
            );
            setThreads((previous) =>
                previous.map((thread) =>
                    thread.project_id === projectId
                        ? { ...thread, project_id: null }
                        : thread,
                ),
            );
        } catch (error) {
            console.error("Failed to delete project:", projectId, error);
        }
    }

    async function handleMoveThread(
        threadId: string,
        projectId: string | null,
    ) {
        if (threadId === DRAFT_THREAD_ID) {
            return;
        }
        try {
            await setSessionProject(threadId, projectId);
            setThreads((previous) =>
                previous.map((thread) =>
                    thread.id === threadId
                        ? { ...thread, project_id: projectId }
                        : thread,
                ),
            );
        } catch (error) {
            console.error("Failed to move thread:", threadId, error);
        }
    }

    return {
        projects,
        setProjects,
        handleCreateProject,
        handleRenameProject,
        handleDeleteProject,
        handleMoveThread,
    };
}
