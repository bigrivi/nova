/** Root component: layout orchestration, modal layer, global keybindings, and command dispatch */
import { CliRenderEvents } from "@opentui/core";
import { useKeyboard, useRenderer } from "@opentui/react";
import { useEffect, useMemo, useState } from "react";
import { getAgent, getPermissions, listSessions } from "../api/nova-api.ts";
import { listPendingSessions } from "../api/nova-api.ts";
import type { NovaPendingSummary } from "../api/types.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useExpandStore } from "../stores/expand-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { cycleMode, normalizeMode, usePermissionStore } from "../stores/permission-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { useTabStore } from "../stores/tab-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { loadModels } from "../lib/catalog.ts";
import { ThemeOverride, useTheme } from "../context/theme.tsx";
import { dimTheme } from "../themes/fx/dim.ts";
import {
    regenerateLastAnswer,
    requestInterrupt,
    submitAskAnswers,
    submitAskCancel,
} from "../stream/chat-stream.ts";
import { startSessionEvents } from "../stream/session-events.ts";
import { ApprovalDialog } from "./ApprovalDialog.tsx";
import { AskUserCard } from "./AskUserCard.tsx";
import { Composer, type ComposerCommandHandler } from "./Composer.tsx";
import { MessageList } from "./MessageList.tsx";
import { AgentsScreen } from "./screens/AgentsScreen.tsx";
import { LaunchFrame } from "./screens/LaunchFrame.tsx";
import { LaunchScreen } from "./screens/LaunchScreen.tsx";
import { buildHints, hintAt, HINT_MS, motionEnabled } from "./screens/launch.ts";
import { CreateAgentScreen } from "./screens/CreateAgentScreen.tsx";
import { CommitScreen } from "./screens/CommitScreen.tsx";
import { MenuOverlay } from "./MenuOverlay.tsx";
import { useMenuStore } from "../stores/menu-store.ts";
import { DiffScreen } from "./screens/DiffScreen.tsx";
import { McpScreen } from "./screens/McpScreen.tsx";
import { MemoryScreen } from "./screens/MemoryScreen.tsx";
import { ConnectProviderScreen } from "./screens/ConnectProviderScreen.tsx";
import { ModelsScreen } from "./screens/ModelsScreen.tsx";
import { PermissionsScreen } from "./screens/PermissionsScreen.tsx";
import { ReviewScreen } from "./screens/ReviewScreen.tsx";
import { RewindScreen } from "./screens/RewindScreen.tsx";
import { SchedulesScreen } from "./screens/SchedulesScreen.tsx";
import { TasksScreen } from "./screens/TasksScreen.tsx";
import { SessionsScreen } from "./screens/SessionsScreen.tsx";
import { ThemeScreen } from "./screens/ThemeScreen.tsx";
import { VariantsScreen } from "./screens/VariantsScreen.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { Toast } from "./Toast.tsx";
import { SessionTabBar } from "./SessionTabBar.tsx";
import { WORKSPACE_DIR } from "../workspace.ts";
import { compactOpenSession } from "../lib/compact-session.ts";
import { forkOpenSession } from "../lib/fork-session.ts";
import { pruneRestoredTabs, restoredActiveSessionId } from "../lib/tab-persistence.ts";
import {
    closeTab,
    cycleTabs,
    focusSession,
    openDraftTab,
    reopenLastClosed,
    selectTab,
    selectTabIndex,
} from "../lib/tab-actions.ts";

export type ExitHandler = () => void;

export function App({ onExit }: { onExit: ExitHandler }) {
    const askQuestions = useAskUserStore((state) => state.active);
    const approval = useApprovalStore((state) => state.pending);
    const screen = useScreenStore((state) => state.current);
    const askTabId = useAskUserStore((state) => state.activeTabId);
    const messages = useChatStore((state) => state.messages);
    const isStreaming = useChatStore((state) => state.isStreaming);
    const sessionId = useChatStore((state) => state.sessionId);
    const provider = useChatStore((state) => state.provider);
    const model = useChatStore((state) => state.model);
    // A null session means nothing has been loaded yet; `loadHistory` sets both
    // fields at once, so picking a session never flashes the launch screen.
    const launching =
        messages.length === 0 && !isStreaming && sessionId === null;
    const [hintIndex, setHintIndex] = useState(0);
    const [savedSessions, setSavedSessions] = useState(0);
    const menuAnchor = useMenuStore((state) => state.anchor);
    const hints = useMemo(() => buildHints(savedSessions), [savedSessions]);
    const theme = useTheme();
    const renderer = useRenderer();
    const animate = motionEnabled(process.env);

    useEffect(() => {
        if (!launching || !animate) return;
        const timer = setInterval(() => {
            setHintIndex((value) => value + 1);
        }, HINT_MS);
        return () => {
            clearInterval(timer);
        };
    }, [launching, animate]);

    // Offering the resume hint needs the count, not the sessions themselves.
    // The same fetch drops restored tabs whose session is gone and refreshes
    // their titles from the backend.
    useEffect(() => {
        let cancelled = false;
        const startupTabs = new Set(
            useTabStore.getState().tabs.map((tab) => tab.id),
        );
        void Promise.all([
            listSessions({ workspaceDir: WORKSPACE_DIR }),
            listPendingSessions().catch(
                (): NovaPendingSummary => ({}),
            ),
        ])
            .then(([sessions, pending]) => {
                if (cancelled) return;
                setSavedSessions(sessions.length);
                pruneRestoredTabs(new Set(sessions.map((session) => session.id)));
                const store = useTabStore.getState();
                for (const session of sessions) {
                    if (session.title) {
                        store.setTitle(session.id, session.title);
                    }
                    const tab = store.tabs.find(
                        (item) => item.sessionId === session.id,
                    );
                    if (tab && startupTabs.has(tab.id) && session.agent_key) {
                        useChatStore
                            .getState()
                            .setAgent(
                                session.agent_key,
                                session.agent_key,
                                tab.id,
                            );
                    }
                }

                // Restored tabs carry the prompt badge before they are opened;
                // the dialog itself waits until the tab is selected.
                for (const tab of useTabStore.getState().tabs) {
                    if (!tab.sessionId) continue;
                    const prompt = pending[tab.sessionId];
                    if (!prompt) continue;
                    useTabStore
                        .getState()
                        .setAttention(
                            tab.id,
                            prompt.ask
                                ? "question"
                                : prompt.approvals > 0
                                  ? "approval"
                                  : null,
                        );
                }

                // Return to the session that was on screen last run, unless the
                // prune removed it or the user already picked something.
                const restored = restoredActiveSessionId();
                if (
                    restored &&
                    useTabStore.getState().tabs.length > 0 &&
                    useTabStore.getState().activeId === null &&
                    useChatStore.getState().sessionId === null
                ) {
                    const tab = useTabStore
                        .getState()
                        .tabs.find((item) => item.sessionId === restored);
                    if (tab) {
                        selectTab(tab.id);
                    }
                }
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    // A translucent scrim eats double-width glyphs, so the transcript is dimmed
    // by recolouring its palette instead of drawing over it.
    const quiet = useMemo(
        () => (screen ? dimTheme(theme) : null),
        [screen, theme],
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

    // A background approval or question owns the modal: bring its tab forward so
    // the dialog and the transcript it refers to cannot disagree.
    useEffect(() => {
        if (approval?.sessionId) {
            focusSession(approval.sessionId);
        }
    }, [approval?.requestId, approval?.sessionId]);

    useEffect(() => {
        if (askQuestions && askTabId) {
            selectTab(askTabId);
        }
    }, [askQuestions, askTabId]);

    // Read the initial provider/model from the agent table on startup to stay in sync with the model selected by the frontend/desktop
    useEffect(() => {
        let cancelled = false;
        void getAgent("main")
            .then((agent) => {
                if (cancelled || !agent?.provider || !agent?.model) {
                    return;
                }
                useChatStore.setState({
                    provider: agent.provider,
                    model: agent.model,
                    reasoningEffort: agent.reasoning_effort ?? "",
                    agentKey: agent.key ?? "main",
                    agentName: agent.name ?? "Nova",
                });
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    // A fresh install ships an empty providers map, so the model picker would be
    // silently empty; say what to do about it instead.
    useEffect(() => {
        let cancelled = false;
        void loadModels()
            .then((models) => {
                if (cancelled || models.length > 0) {
                    return;
                }
                useToastStore
                    .getState()
                    .show(
                        "No provider configured. Add one to ~/.nova/config.json (or the web UI).",
                        6000,
                    );
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    // Start from the mode in permissions.json; a later Shift+Tab overrides it
    // for the rest of the session without touching the file.
    useEffect(() => {
        let cancelled = false;
        void getPermissions(WORKSPACE_DIR)
            .then((policy) => {
                if (cancelled) return;
                const store = usePermissionStore.getState();
                store.setPolicy(policy);
                store.setMode(normalizeMode(policy.mode));
            })
            .catch(() => {});
        return () => {
            cancelled = true;
        };
    }, []);

    useKeyboard((key) => {
        if (
            useAskUserStore.getState().active ||
            useApprovalStore.getState().pending
        ) {
            // Modal keyboard is handled by AskUserCard / ApprovalDialog
            return;
        }
        // Before the screen guard: the mode belongs to the session, so it stays
        // switchable from any screen, not just an empty composer.
        // Ctrl+Tab is checked first: ctrl+shift+tab must not fall through to the
        // permission-mode cycle below.
        if (key.ctrl && key.name === "tab") {
            cycleTabs(key.shift ? -1 : 1);
            return;
        }
        if ((key.meta || key.option) && (key.name === "down" || key.name === "up")) {
            cycleTabs(key.name === "down" ? 1 : -1);
            return;
        }
        if (key.shift && key.name === "tab") {
            cycleMode();
            return;
        }
        if (useScreenStore.getState().current) {
            // Screen keyboard is handled by each screen's useKeyboard
            return;
        }
        if (key.ctrl && key.name === "w") {
            closeTab();
            return;
        }
        if (key.ctrl && key.name === "t") {
            // Ctrl+Shift+T only reaches us as distinct on terminals that encode
            // the modifier; /reopen covers the rest.
            if (key.shift) {
                reopenLastClosed();
            } else {
                openDraftTab();
            }
            return;
        }
        if (key.ctrl && key.name >= "1" && key.name <= "9") {
            selectTabIndex(Number(key.name) - 1);
            return;
        }
        if (key.ctrl && key.name === "o") {
            useExpandStore.getState().toggle();
            return;
        }
        if (key.ctrl && key.name === "c") {
            onExit();
        }
        if (key.name === "escape") {
            void requestInterrupt();
        }
    });

    const handleCommand: ComposerCommandHandler = (id, _args) => {
        const screens = useScreenStore.getState();
        switch (id) {
            case "new":
                openDraftTab();
                return;
            case "close":
                closeTab();
                return;
            case "reopen":
                if (!reopenLastClosed()) {
                    useToastStore
                        .getState()
                        .show("No closed tab to reopen", 3000);
                }
                return;
            case "clear":
                useChatStore.getState().clearMessages();
                useCtxStore.getState().clear();
                return;
            case "quit":
            case "exit":
                onExit();
                return;
            case "sessions":
                screens.open({ kind: "sessions" });
                return;
            case "connect":
                screens.open({ kind: "connect-provider" });
                return;
            case "models":
                screens.open({ kind: "models" });
                return;
            case "agents":
                screens.open({ kind: "agents" });
                return;
            case "create-agent":
                screens.open({ kind: "create-agent" });
                return;
            case "delete-agent":
                screens.open({ kind: "delete-agent" });
                return;
            case "variants": {
                const current = useChatStore.getState();
                void loadModels()
                    .then((models) => {
                        const match = models.find(
                            (m) =>
                                m.provider === current.provider &&
                                m.model === current.model,
                        );
                        if (!match || match.efforts.length === 0) {
                            useToastStore
                                .getState()
                                .show(
                                    "this model has no reasoning effort levels configured",
                                    3000,
                                );
                            return;
                        }
                        screens.open({ kind: "variants" });
                    })
                    .catch(() => screens.open({ kind: "variants" }));
                return;
            }
            case "themes":
                screens.open({ kind: "theme" });
                return;
            case "permissions":
                screens.open({ kind: "permissions" });
                return;
            case "rewind":
                screens.open({ kind: "rewind" });
                return;
            case "tasks":
                screens.open({ kind: "tasks" });
                return;
            case "schedules":
                screens.open({ kind: "schedules" });
                return;
            case "diff":
                screens.open({ kind: "diff" });
                return;
            case "review":
                screens.open({ kind: "review" });
                return;
            case "commit":
                screens.open({ kind: "commit" });
                return;
            case "mcp":
                screens.open({ kind: "mcp" });
                return;
            case "memory":
                screens.open({ kind: "memory" });
                return;
            case "fork":
                void forkOpenSession()
                    .then((message) => {
                        useToastStore.getState().show(message, 3000);
                    })
                    .catch((err: unknown) => {
                        useToastStore
                            .getState()
                            .show(
                                `Fork failed: ${err instanceof Error ? err.message : String(err)}`,
                                4000,
                            );
                    });
                return;
            case "regenerate":
                void regenerateLastAnswer();
                return;
            case "compact":
                void compactOpenSession()
                    .then((message) => {
                        useToastStore.getState().show(message, 3000);
                    })
                    .catch((err: unknown) => {
                        useToastStore
                            .getState()
                            .show(
                                `Compact failed: ${err instanceof Error ? err.message : String(err)}`,
                                4000,
                            );
                    });
                return;
            default:
                // /install-skill /install-global-skill → not implemented yet
                return;
        }
    };

    return (
        <box
            width="100%"
            height="100%"
            flexDirection="column"
            flexGrow={1}
            padding={0}
            gap={0}
            marginBottom={1}
            backgroundColor={theme.background.base}
        >
            <ThemeOverride value={quiet}>
                <SessionTabBar />
                {launching ? null : <MessageList />}
                {askQuestions ? (
                    <AskUserCard
                        questions={askQuestions}
                        onSubmit={(answers) => {
                            void submitAskAnswers(askQuestions, answers);
                        }}
                        onCancel={() => submitAskCancel(askQuestions)}
                    />
                ) : approval ? (
                    <ApprovalDialog pending={approval} />
                ) : (
                    // One wrapper for both layouts: only its props change, so the
                    // composer (and any draft inside it) survives the switch.
                    <box
                        flexDirection="column"
                        flexGrow={launching ? 1 : 0}
                        flexShrink={0}
                        justifyContent={launching ? "center" : "flex-start"}
                        alignItems={launching ? "center" : "stretch"}
                    >
                        {launching ? <LaunchScreen /> : null}
                        <LaunchFrame active={launching}>
                            <Composer
                                onCommand={handleCommand}
                                variant={launching ? "card" : "bar"}
                                placeholder={
                                    launching
                                        ? animate
                                            ? hintAt(hintIndex, hints)
                                            : hints[0]
                                        : undefined
                                }
                            />
                        </LaunchFrame>
                        {launching && (!provider || !model) ? (
                            <box marginTop={1}>
                                <text
                                    fg={theme.feedback.running}
                                    content="No model selected — type /models"
                                />
                            </box>
                        ) : null}
                    </box>
                )}
                <StatusBar />
            </ThemeOverride>
            {screen?.kind === "sessions" ? <SessionsScreen /> : null}
            {screen?.kind === "theme" ? <ThemeScreen /> : null}
            {screen?.kind === "variants" ? <VariantsScreen /> : null}
            {screen?.kind === "models" ? <ModelsScreen /> : null}
            {screen?.kind === "connect-provider" ? (
                <ConnectProviderScreen />
            ) : null}
            {screen?.kind === "agents" || screen?.kind === "delete-agent" ? (
                <AgentsScreen deletable={screen.kind === "delete-agent"} />
            ) : null}
            {screen?.kind === "create-agent" ? <CreateAgentScreen /> : null}
            {screen?.kind === "permissions" ? <PermissionsScreen /> : null}
            {screen?.kind === "rewind" ? <RewindScreen /> : null}
            {screen?.kind === "tasks" ? <TasksScreen /> : null}
            {screen?.kind === "schedules" ? <SchedulesScreen /> : null}
            {screen?.kind === "mcp" ? <McpScreen /> : null}
            {screen?.kind === "memory" ? <MemoryScreen /> : null}
            {screen?.kind === "diff" ? <DiffScreen /> : null}
            {screen?.kind === "review" ? <ReviewScreen /> : null}
            {screen?.kind === "commit" ? <CommitScreen /> : null}
            <MenuOverlay
                anchorY={menuAnchor.y}
                anchorX={menuAnchor.x}
                anchorWidth={menuAnchor.width}
                anchorEdgeY={menuAnchor.edgeY}
            />
            <Toast />
        </box>
    );
}
