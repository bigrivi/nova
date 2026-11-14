/** Startup requests: the main agent, the permission mode, and the model list.
 *
 *  Each one is independent and none of them may hold up the first frame.
 */
import { useEffect } from "react";

import { CliRenderEvents } from "@opentui/core";
import { useRenderer } from "@opentui/react";

import { getAgent, getPermissions } from "../api/nova-api.ts";
import { useTheme } from "../context/theme.tsx";
import { loadModels } from "../lib/catalog.ts";
import { logWarn } from "../lib/errors.ts";
import {
    normalizeMode,
    usePermissionStore,
} from "../stores/permission-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { startSessionEvents } from "../stream/session-events.ts";
import { WORKSPACE_DIR } from "../workspace.ts";
import { useAsyncOnMount } from "./useAsyncOnMount.ts";

export function useAppBootstrap(): void {
    const renderer = useRenderer();
    const theme = useTheme();

    // Read the initial provider/model from the agent table on startup to stay
    // in sync with the model selected by the frontend/desktop
    useAsyncOnMount(
        () =>
            getAgent("main").catch((err: unknown) => {
                logWarn("loading the main agent failed", err);
                return null;
            }),
        (agent) => {
            if (!agent?.provider || !agent?.model) {
                return;
            }
            useChatStore.setState({
                provider: agent.provider,
                model: agent.model,
                reasoningEffort: agent.reasoning_effort ?? "",
                agentKey: agent.key ?? "main",
                agentName: agent.name ?? "Nova",
            });
        },
    );

    // Start from the mode in permissions.json; a later Shift+Tab overrides it
    // for the rest of the session without touching the file.
    useAsyncOnMount(
        () =>
            getPermissions(WORKSPACE_DIR).catch((err: unknown) => {
                logWarn("loading the permission policy failed", err);
                return null;
            }),
        (policy) => {
            if (!policy) return;
            const store = usePermissionStore.getState();
            store.setPolicy(policy);
            store.setMode(normalizeMode(policy.mode));
        },
    );

    // A fresh install ships an empty providers map, so the model picker would
    // be silently empty; say what to do about it instead. A list that failed
    // to load is not an empty list, so it says nothing.
    useAsyncOnMount(
        () =>
            loadModels().catch((err: unknown) => {
                logWarn("loading the model list failed", err);
                return null;
            }),
        (models) => {
            if (!models || models.length > 0) {
                return;
            }
            useToastStore
                .getState()
                .show(
                    "No provider configured. Add one to ~/.nova/config.json (or the web UI).",
                    6000,
                );
        },
    );

    useEffect(() => {
        renderer.setBackgroundColor(theme.background.base);
    }, [renderer, theme.background.base]);

    // Tail server-initiated turns so a background-task wake appears in place.
    useEffect(() => startSessionEvents(), []);

    // A blurred terminal does not count as viewing the active tab, so a turn
    // that finishes while the window is in the background keeps its unread dot.
    useEffect(() => {
        const onFocus = (): void => useTabStore.getState().setFocused(true);
        const onBlur = (): void => useTabStore.getState().setFocused(false);
        renderer.on(CliRenderEvents.FOCUS, onFocus);
        renderer.on(CliRenderEvents.BLUR, onBlur);
        return () => {
            renderer.off(CliRenderEvents.FOCUS, onFocus);
            renderer.off(CliRenderEvents.BLUR, onBlur);
        };
    }, [renderer]);
}
