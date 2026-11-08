import { StatusBar } from "expo-status-bar";
import { useEffect, useRef } from "react";
import { AppState, StyleSheet, Text, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { openDraftTab, openSessionTab } from "./src/lib/tab-actions";
import {
    bootstrapWorkspace,
    flushWorkspace,
    resetWorkspace,
} from "./src/lib/workspace";
import {
    startSessionEvents,
    stopSessionEvents,
} from "./src/lib/session-events";
import { ChatScreen } from "./src/screens/ChatScreen";
import { ConnectScreen } from "./src/screens/ConnectScreen";
import { SessionsScreen } from "./src/screens/SessionsScreen";
import { SettingsScreen } from "./src/screens/SettingsScreen";
import { useConnection } from "./src/state/connection";
import { useSessions } from "./src/state/sessions";
import { useRoute } from "./src/state/route";
import { useTabs } from "./src/state/tabs";
import { useUi } from "./src/state/ui";
import { useTheme } from "./src/theme/useTheme";

function Splash() {
    const { theme } = useTheme();
    return (
        <View style={[styles.splash, { backgroundColor: theme.background }]}>
            <Text style={[styles.splashText, { color: theme.foreground }]}>
                Nova
            </Text>
        </View>
    );
}

export default function App() {
    const { theme } = useTheme();
    const status = useConnection((state) => state.status);
    const hydrate = useConnection((state) => state.hydrate);
    const screen = useUi((state) => state.screen);
    const setScreen = useUi((state) => state.setScreen);
    const bootstrapped = useRef<string | null>(null);

    useEffect(() => {
        void hydrate();
    }, [hydrate]);

    useEffect(() => {
        const subscription = AppState.addEventListener("change", (next) => {
            const active = next === "active";
            useTabs
                .getState()
                .setFocused(active && useUi.getState().screen === "chat");
            if (!active) {
                flushWorkspace();
                stopSessionEvents();
                return;
            }
            if (useConnection.getState().status === "connected") {
                startSessionEvents();
            }
        });
        return () => subscription.remove();
    }, []);

    useEffect(() => {
        useTabs
            .getState()
            .setFocused(
                screen === "chat" && AppState.currentState === "active",
            );
    }, [screen]);

    useEffect(() => {
        if (status !== "connected") {
            if (status === "disconnected") {
                bootstrapped.current = null;
                resetWorkspace();
                setScreen("sessions");
            }
            return;
        }
        const connection = useConnection.getState();
        const key = `${connection.baseUrl}|${connection.username}`;
        if (bootstrapped.current === key) {
            return;
        }
        bootstrapped.current = key;
        void bootstrapWorkspace()
            .then(() => {
                const hasActive = useTabs.getState().activeId !== null;
                setScreen(hasActive ? "chat" : "sessions");
            })
            .catch((error: unknown) => {
                console.warn("Workspace bootstrap failed", error);
                setScreen("sessions");
            });
    }, [status, setScreen]);

    let content: React.ReactNode;
    if (status === "loading") {
        content = <Splash />;
    } else if (status !== "connected") {
        content = <ConnectScreen />;
    } else if (screen === "settings") {
        content = <SettingsScreen onBack={() => setScreen("sessions")} />;
    } else if (screen === "chat") {
        content = (
            <ChatScreen
                onBack={() => {
                    void useSessions.getState().refresh();
                    setScreen("sessions");
                }}
            />
        );
    } else {
        content = (
            <SessionsScreen
                onOpen={(session) => {
                    openSessionTab(session.id, session.title, session.agent_key, session.project_id);
                    setScreen("chat");
                }}
                onNew={() => {
                    useRoute.getState().setProjectId(null);
                    openDraftTab();
                    setScreen("chat");
                }}
                onNewInProject={(projectId) => {
                    openDraftTab();
                    useRoute.getState().setProjectId(projectId);
                    setScreen("chat");
                }}
                onSettings={() => setScreen("settings")}
            />
        );
    }

    return (
        <SafeAreaProvider>
            <StatusBar style="auto" />
            <View
                style={[
                    styles.root,
                    { backgroundColor: theme.background },
                ]}
            >
                {content}
            </View>
        </SafeAreaProvider>
    );
}

const styles = StyleSheet.create({
    root: { flex: 1 },
    splash: {
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
    },
    splashText: {
        fontSize: 28,
        fontWeight: "700",
    },
});
