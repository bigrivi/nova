/** Screen routing: renders whichever screen the store says is open. */
import type { ReactNode } from "react";
import { useScreenStore } from "../../stores/screen-store.ts";
import { AgentsScreen } from "./AgentsScreen.tsx";
import { CommitScreen } from "./CommitScreen.tsx";
import { ConnectProviderScreen } from "./ConnectProviderScreen.tsx";
import { CreateAgentScreen } from "./CreateAgentScreen.tsx";
import { DiffScreen } from "./DiffScreen.tsx";
import { CopyCodeBlockScreen } from "./CopyCodeBlockScreen.tsx";
import { EditScreen } from "./EditScreen.tsx";
import { MessageActionsScreen } from "./MessageActionsScreen.tsx";
import { StatsScreen } from "./StatsScreen.tsx";
import { McpScreen } from "./McpScreen.tsx";
import { MemoryScreen } from "./MemoryScreen.tsx";
import { ModelsScreen } from "./ModelsScreen.tsx";
import { PermissionsScreen } from "./PermissionsScreen.tsx";
import { ReviewScreen } from "./ReviewScreen.tsx";
import { RewindScreen } from "./RewindScreen.tsx";
import { SchedulesScreen } from "./SchedulesScreen.tsx";
import { SessionsScreen } from "./SessionsScreen.tsx";
import { TasksScreen } from "./TasksScreen.tsx";
import { ThemeScreen } from "./ThemeScreen.tsx";
import { VariantsScreen } from "./VariantsScreen.tsx";

/** The screen that is currently open */
type ActiveScreen = NonNullable<
    ReturnType<typeof useScreenStore.getState>["current"]
>;

// Record, not a partial map: a new screen kind fails to compile until it is
// mapped here.
const SCREENS: Record<
    ActiveScreen["kind"],
    (screen: ActiveScreen) => ReactNode
> = {
    sessions: () => <SessionsScreen />,
    theme: () => <ThemeScreen />,
    variants: () => <VariantsScreen />,
    models: () => <ModelsScreen />,
    "connect-provider": () => <ConnectProviderScreen />,
    agents: () => <AgentsScreen deletable={false} />,
    "delete-agent": (screen) => (
        <AgentsScreen deletable={screen.kind === "delete-agent"} />
    ),
    "create-agent": () => <CreateAgentScreen />,
    permissions: () => <PermissionsScreen />,
    rewind: () => <RewindScreen />,
    edit: () => <EditScreen />,
    "copy-code-block": (screen) => {
        if (screen.kind !== "copy-code-block") return null;
        return <CopyCodeBlockScreen blocks={screen.blocks} />;
    },
    "message-actions": (screen) => {
        if (screen.kind !== "message-actions") return null;
        return (
            <MessageActionsScreen messageId={screen.messageId} text={screen.text} />
        );
    },
    stats: () => <StatsScreen />,
    tasks: () => <TasksScreen />,
    schedules: () => <SchedulesScreen />,
    mcp: () => <McpScreen />,
    memory: () => <MemoryScreen />,
    diff: () => <DiffScreen />,
    review: () => <ReviewScreen />,
    commit: () => <CommitScreen />,
};

export function ScreenHost() {
    const screen = useScreenStore((state) => state.current);
    if (!screen) return null;
    return SCREENS[screen.kind](screen);
}
