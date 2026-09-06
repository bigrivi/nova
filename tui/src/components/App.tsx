/** Root component: layout orchestration, modal layer, global keybindings, and command dispatch */
import { useKeyboard } from "@opentui/react";
import { useEffect } from "react";
import { getAgent } from "../api/nova-api.ts";
import { useApprovalStore } from "../stores/approval-store.ts";
import { useAskUserStore } from "../stores/ask-user-store.ts";
import { useChatStore } from "../stores/chat-store.ts";
import { useCtxStore } from "../stores/ctx-store.ts";
import { useScreenStore } from "../stores/screen-store.ts";
import { submitAskAnswers, submitAskCancel } from "../stream/chat-stream.ts";
import { ApprovalDialog } from "./ApprovalDialog.tsx";
import { AskUserCard } from "./AskUserCard.tsx";
import { Composer, type ComposerCommandHandler } from "./Composer.tsx";
import { MessageList } from "./MessageList.tsx";
import { AgentsScreen } from "./screens/AgentsScreen.tsx";
import { CreateAgentScreen } from "./screens/CreateAgentScreen.tsx";
import { ModelsScreen } from "./screens/ModelsScreen.tsx";
import { SessionsScreen } from "./screens/SessionsScreen.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { Toast } from "./Toast.tsx";

export type ExitHandler = () => void;

export function App({ onExit }: { onExit: ExitHandler }) {
    const askQuestions = useAskUserStore((state) => state.active);
    const approval = useApprovalStore((state) => state.pending);
    const screen = useScreenStore((state) => state.current);

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
            case "list-agents":
                screens.open({ kind: "agents" });
                return;
            case "create-agent":
                screens.open({ kind: "create-agent" });
                return;
            case "delete-agent":
                screens.open({ kind: "delete-agent" });
                return;
            default:
                // /theme /install-skill /install-global-skill → not implemented yet
                return;
        }
    };

    // TodoPanel intentionally not rendered here — the persistent panel above
    // Composer was crowded/duplicated the todo_write ToolBlock summary line;
    // file kept for future overlay use, history visible via MessageList.
    return (
        <box
            flexDirection="column"
            flexGrow={1}
            padding={0}
            gap={0}
            marginBottom={1}
        >
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
                <ApprovalDialog
                    sessionId={approval.sessionId}
                    requestId={approval.requestId}
                    command={approval.command}
                    description={approval.description}
                />
            ) : (
                <Composer onCommand={handleCommand} />
            )}
            <StatusBar />
            {screen?.kind === "sessions" ? <SessionsScreen /> : null}
            {screen?.kind === "models" ? <ModelsScreen /> : null}
            {screen?.kind === "agents" || screen?.kind === "delete-agent" ? (
                <AgentsScreen deletable={screen.kind === "delete-agent"} />
            ) : null}
            {screen?.kind === "create-agent" ? <CreateAgentScreen /> : null}
            <Toast />
        </box>
    );
}
