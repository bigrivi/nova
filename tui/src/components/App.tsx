/** Root component: layout orchestration, modal layer, global keybindings, and command dispatch */
import { useKeyboard, useRenderer } from "@opentui/react";
import { useEffect, useMemo } from "react";
import { getAgent, listModels } from "../api/nova-api.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useExpandStore } from "../stores/expand-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { useToastStore } from "../stores/toast-store.ts";
import { ThemeOverride, useTheme } from "../context/theme.tsx";
import { dimTheme } from "../themes/dim.ts";
import { submitAskAnswers, submitAskCancel } from "../stream/chat-stream.ts";
import { startSessionEvents } from "../stream/session-events.ts";
import { ApprovalDialog } from "./ApprovalDialog.tsx";
import { AskUserCard } from "./AskUserCard.tsx";
import { Composer, type ComposerCommandHandler } from "./Composer.tsx";
import { MessageList } from "./MessageList.tsx";
import { AgentsScreen } from "./screens/AgentsScreen.tsx";
import { CreateAgentScreen } from "./screens/CreateAgentScreen.tsx";
import { ModelsScreen } from "./screens/ModelsScreen.tsx";
import { SessionsScreen } from "./screens/SessionsScreen.tsx";
import { ThemeScreen } from "./screens/ThemeScreen.tsx";
import { VariantsScreen } from "./screens/VariantsScreen.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { Toast } from "./Toast.tsx";

export type ExitHandler = () => void;

export function App({ onExit }: { onExit: ExitHandler }) {
    const askQuestions = useAskUserStore((state) => state.active);
    const approval = useApprovalStore((state) => state.pending);
    const screen = useScreenStore((state) => state.current);
    const theme = useTheme();
    const renderer = useRenderer();
    // A translucent scrim eats double-width glyphs, so the transcript is dimmed
    // by recolouring its palette instead of drawing over it.
    const quiet = useMemo(
        () => (screen ? dimTheme(theme) : null),
        [screen, theme],
    );

    useEffect(() => {
        renderer.setBackgroundColor(theme.background);
    }, [renderer, theme.background]);

    // Tail server-initiated turns so a background-task wake appears in place.
    useEffect(() => startSessionEvents(), []);

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

    useKeyboard((key) => {
        if (
            useAskUserStore.getState().active ||
            useApprovalStore.getState().pending
        ) {
            // Modal keyboard is handled by AskUserCard / ApprovalDialog
            return;
        }
        if (useScreenStore.getState().current) {
            // Screen keyboard is handled by each screen's useKeyboard
            return;
        }
        if (key.ctrl && key.name === "o") {
            useExpandStore.getState().toggle();
            return;
        }
        if (key.ctrl && key.name === "c") {
            onExit();
        }
    });

    const handleCommand: ComposerCommandHandler = (id, _args) => {
        const screens = useScreenStore.getState();
        switch (id) {
            case "new":
                useChatStore.getState().reset();
                useCtxStore.getState().clear();
                return;
            case "clear":
                useChatStore.setState({ messages: [] });
                useCtxStore.getState().clear();
                return;
            case "quit":
            case "exit":
                onExit();
                return;
            case "sessions":
                screens.open({ kind: "sessions" });
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
                void listModels()
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
            backgroundColor={theme.background}
        >
            <ThemeOverride value={quiet}>
                <MessageList />
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
                    <Composer onCommand={handleCommand} />
                )}
                <StatusBar />
            </ThemeOverride>
            {screen?.kind === "sessions" ? <SessionsScreen /> : null}
            {screen?.kind === "theme" ? <ThemeScreen /> : null}
            {screen?.kind === "variants" ? <VariantsScreen /> : null}
            {screen?.kind === "models" ? <ModelsScreen /> : null}
            {screen?.kind === "agents" || screen?.kind === "delete-agent" ? (
                <AgentsScreen deletable={screen.kind === "delete-agent"} />
            ) : null}
            {screen?.kind === "create-agent" ? <CreateAgentScreen /> : null}
            <Toast />
        </box>
    );
}
