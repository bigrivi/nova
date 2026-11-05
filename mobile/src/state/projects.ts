/** Projects: the folders sessions are grouped under. */
import { create } from "zustand";

import {
    createProject as createProjectApi,
    deleteProject as deleteProjectApi,
    listProjects,
    setSessionProject,
    updateProject as updateProjectApi,
} from "../api/client";
import type { NovaProject } from "../api/types";
import { useSessions } from "./sessions";

type ProjectsState = {
    items: NovaProject[];
    loading: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    create: (name: string, path?: string | null) => Promise<NovaProject | null>;
    rename: (
        projectId: string,
        name: string,
        path?: string | null,
    ) => Promise<void>;
    remove: (projectId: string) => Promise<void>;
    moveSession: (
        sessionId: string,
        projectId: string | null,
    ) => Promise<void>;
    reset: () => void;
};

export const useProjects = create<ProjectsState>((set, get) => ({
    items: [],
    loading: false,
    error: null,

    refresh: async () => {
        set({ loading: true, error: null });
        try {
            const items = await listProjects();
            set({ items, loading: false });
        } catch (error) {
            set({
                loading: false,
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not load projects",
            });
        }
    },

    create: async (name, path = null) => {
        try {
            const project = await createProjectApi(name, path);
            set((state) => ({ items: [project, ...state.items] }));
            return project;
        } catch (error) {
            set({
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not create the project",
            });
            return null;
        }
    },

    rename: async (projectId, name, path) => {
        try {
            const project = await updateProjectApi(projectId, {
                name,
                ...(path !== undefined ? { path } : {}),
            });
            set((state) => ({
                items: state.items.map((item) =>
                    item.id === projectId ? project : item,
                ),
            }));
        } catch (error) {
            set({
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not rename the project",
            });
        }
    },

    remove: async (projectId) => {
        try {
            await deleteProjectApi(projectId);
            set((state) => ({
                items: state.items.filter((item) => item.id !== projectId),
            }));
            useSessions.setState((state) => ({
                items: state.items.map((item) =>
                    item.project_id === projectId
                        ? { ...item, project_id: null }
                        : item,
                ),
            }));
        } catch (error) {
            set({
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not delete the project",
            });
        }
    },

    moveSession: async (sessionId, projectId) => {
        if (!get().items.some((item) => item.id === projectId) && projectId) {
            return;
        }
        try {
            await setSessionProject(sessionId, projectId);
            useSessions.setState((state) => ({
                items: state.items.map((item) =>
                    item.id === sessionId
                        ? { ...item, project_id: projectId }
                        : item,
                ),
            }));
        } catch (error) {
            set({
                error:
                    error instanceof Error
                        ? error.message
                        : "Could not move the session",
            });
        }
    },

    reset: () => set({ items: [], loading: false, error: null }),
}));
