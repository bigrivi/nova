import Feather from "@expo/vector-icons/Feather";
import { useEffect, useMemo, useState } from "react";
import * as Clipboard from "expo-clipboard";
import {
    Alert,
    BackHandler,
    KeyboardAvoidingView,
    Pressable,
    Share,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ActionSheet } from "../components/ActionSheet";
import { ApprovalSheet, InputNotice } from "../components/ApprovalSheet";
import { AskUserSheet } from "../components/AskUserSheet";
import { BackgroundTasksPanel } from "../components/BackgroundTasksPanel";
import { CompactionBanner } from "../components/CompactionBanner";
import { TodoProgressPanel } from "../components/TodoProgressPanel";
import { Composer } from "../components/Composer";
import { MessageList } from "../components/MessageList";
import { PickerSheet } from "../components/PickerSheet";
import { TabOverviewSheet } from "../components/TabOverviewSheet";
import { TabStrip } from "../components/TabStrip";
import {
    cancelBackgroundTask,
    setSessionRoute,
} from "../api/client";
import {
    pickDocumentAttachment,
    pickImageAttachment,
    readClipboardImage,
} from "../lib/attachments";
import { selectableSubagents } from "../chat/mention";
import { modelPickerSections } from "../chat/models";
import { transcriptText } from "../chat/transcript";
import { useAttachments } from "../state/attachments";
import {
    closeTab,
    ensureLoaded,
    openDraftTab,
    selectTab,
} from "../lib/tab-actions";
import {
    approveTab,
    cancelAsk,
    interruptTab,
    regenerateTurn,
    runTurn,
    submitAskAnswers,
} from "../lib/stream-runner";
import { useChat } from "../state/chat";
import { useCatalog } from "../state/catalog";
import { useChatProgress } from "../state/chat-progress";
import { useProjects } from "../state/projects";
import { useRoute } from "../state/route";
import { useSessions } from "../state/sessions";
import { useTasks } from "../state/tasks";
import { useTabs } from "../state/tabs";
import { useTheme } from "../theme/useTheme";

const EMPTY_TASKS: never[] = [];

export function ChatScreen({ onBack }: { onBack: () => void }) {
    const { theme } = useTheme();
    const insets = useSafeAreaInsets();
    const tabs = useTabs((state) => state.tabs);
    const activeId = useTabs((state) => state.activeId);
    const active = tabs.find((tab) => tab.id === activeId) ?? null;
    const slice = useChat((state) =>
        activeId ? state.byId[activeId] : undefined,
    );
    const progress = useChatProgress((state) =>
        activeId ? state.byId[activeId] : undefined,
    );
    const models = useCatalog((state) => state.models);
    const agents = useCatalog((state) => state.agents);
    const sessions = useSessions((state) => state.items);
    const routeModelId = useRoute((state) => state.modelId);
    const routeAgentKey = useRoute((state) => state.agentKey);
    const routeProjectId = useRoute((state) => state.projectId);
    const routeEffort = useRoute((state) => state.reasoningEffort);
    const projects = useProjects((state) => state.items);
    const [picker, setPicker] = useState<
        "model" | "agent" | "project" | "effort" | null
    >(null);
    const [overviewOpen, setOverviewOpen] = useState(false);
    const [attachOpen, setAttachOpen] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);

    useEffect(() => {
        if (activeId) {
            void ensureLoaded(activeId);
        }
    }, [activeId]);

    useEffect(() => {
        const subscription = BackHandler.addEventListener(
            "hardwareBackPress",
            () => {
                onBack();
                return true;
            },
        );
        return () => subscription.remove();
    }, [onBack]);

    const addAttachment = async (
        source: "library" | "camera" | "document" | "clipboard",
    ) => {
        if (!active) {
            return;
        }
        try {
            const attachment =
                source === "library" || source === "camera"
                    ? await pickImageAttachment(source)
                    : source === "document"
                      ? await pickDocumentAttachment()
                      : await readClipboardImage();
            if (attachment) {
                useAttachments.getState().add(active.id, attachment);
            }
        } catch (error) {
            Alert.alert(
                "Could not add attachment",
                error instanceof Error ? error.message : String(error),
            );
        }
    };

    const newDraft = () => {
        useRoute.getState().setProjectId(null);
        openDraftTab();
    };

    const handleClose = (tabId: string) => {
        const next = closeTab(tabId);
        if (!next) {
            onBack();
        }
    };

    const messages = slice?.messages ?? [];
    const streaming = slice?.streaming ?? false;
    const modelId = active?.sessionId
        ? (slice?.modelId ?? null)
        : routeModelId;
    const sessionEffort = active?.sessionId
        ? (slice?.effort ?? null)
        : routeEffort;
    const activeSessionId = slice?.sessionId ?? active?.sessionId ?? null;
    const tasks = useTasks((state) =>
        activeSessionId
            ? (state.bySession[activeSessionId] ?? EMPTY_TASKS)
            : EMPTY_TASKS,
    );
    const approval = progress?.approval ?? null;
    const ask = progress?.ask ?? null;
    const requiresInput = progress?.requiresInput ?? null;
    const hasPanels =
        (progress?.compacting ?? false) ||
        (progress?.todos?.length ?? 0) > 0 ||
        tasks.length > 0;

    const modelSections = useMemo(
        () => modelPickerSections(models),
        [models],
    );
    const selectedModel =
        models.find((model) => model.id === modelId) ?? null;
    const activeAgentKey =
        active?.sessionId === null
            ? routeAgentKey
            : (slice?.agentKey ?? null);
    const activeAgent =
        agents.find((agent) => agent.key === activeAgentKey) ?? null;
    const agentLabel = activeAgent
        ? `@${activeAgent.name || activeAgent.key}`
        : activeAgentKey
          ? `@${activeAgentKey}`
          : "Nova";
    const modelLabel = selectedModel?.label ?? "Default model";
    const efforts = selectedModel?.efforts ?? [];
    const activeEffort =
        sessionEffort && efforts.includes(sessionEffort)
            ? sessionEffort
            : null;
    const canPickAgent = active?.sessionId === null;
    const mainAgentKey =
        active?.sessionId === null
            ? (routeAgentKey ?? "main")
            : (slice?.agentKey ?? "main");
    const subagents = selectableSubagents(agents, mainAgentKey);
    const sessionProjectId = active?.sessionId
        ? (sessions.find((session) => session.id === active.sessionId)
              ?.project_id ?? null)
        : null;
    const activeProjectId =
        active?.sessionId === null
            ? (slice?.projectId ?? routeProjectId)
            : (sessionProjectId ?? slice?.projectId ?? null);
    const activeProject =
        projects.find((project) => project.id === activeProjectId) ?? null;
    const projectLabel = activeProject?.name ?? null;
    const canClearProject = activeProjectId !== null;

    const composer = active ? (
        <Composer
            key={active.id}
            tabId={active.id}
            streaming={streaming}
            context={progress?.context ?? null}
            route={{
                agentLabel,
                modelLabel,
                effortLabel: activeEffort,
                projectLabel,
                canPickAgent,
                canPickEffort:
                    active?.sessionId === null && efforts.length > 0,
                canPickProject: active !== null,
                canClearProject,
                subagents,
                onPickAgent: () => setPicker("agent"),
                onPickModel: () => setPicker("model"),
                onPickEffort: () => setPicker("effort"),
                onPickProject: () => setPicker("project"),
                onClearProject: () => {
                    if (!active) {
                        return;
                    }
                    useRoute.getState().setProjectId(null);
                    useChat.getState().setProjectId(active.id, null);
                    if (active.sessionId) {
                        void useProjects
                            .getState()
                            .moveSession(active.sessionId, null);
                    }
                },
            }}
            actions={{
                onAddAttachment: () => setAttachOpen(true),
                onSend: (text, attachments) =>
                    runTurn(active.id, text, attachments),
                onStop: () => void interruptTab(active.id),
            }}
            showDisclaimer={messages.length === 0}
        />
    ) : null;

    const footer = !active ? null : approval ? (
        <ApprovalSheet
            approval={approval}
            onResolve={(approved, remember) => {
                void approveTab({
                    tabId: active.id,
                    approved,
                    remember,
                });
            }}
        />
    ) : ask ? (
        <AskUserSheet
            questions={ask}
            onSubmit={(answers) => submitAskAnswers(active.id, answers)}
            onCancel={() => cancelAsk(active.id)}
        />
    ) : requiresInput ? (
        <InputNotice message={requiresInput} />
    ) : (
        composer
    );

    return (
        <View style={[styles.safe, { backgroundColor: theme.background }]}>
            <View style={[styles.topBar, { paddingTop: insets.top + 4 }]}>
                <Pressable
                    onPress={onBack}
                    style={styles.back}
                    accessibilityRole="button"
                    accessibilityLabel="Back to sessions"
                    hitSlop={8}
                >
                    <Feather
                        name="chevron-left"
                        size={22}
                        color={theme.foreground}
                    />
                </Pressable>
                <Text
                    numberOfLines={1}
                    style={[styles.topTitle, { color: theme.foreground }]}
                >
                    {active?.title ?? "Nova"}
                </Text>
                {messages.length > 0 ? (
                    <Pressable
                        onPress={() => setMenuOpen(true)}
                        style={styles.more}
                        accessibilityRole="button"
                        accessibilityLabel="Conversation actions"
                    >
                        <Feather
                            name="more-horizontal"
                            size={18}
                            color={theme.weakStrong}
                        />
                    </Pressable>
                ) : null}
            </View>

            <TabStrip
                tabs={tabs}
                activeId={activeId}
                onSelect={selectTab}
                onClose={handleClose}
                onNew={newDraft}
                onOverview={() => setOverviewOpen(true)}
            />

            <KeyboardAvoidingView
                style={styles.flex}
                behavior="padding"
            >
                {messages.length === 0 ? (
                    <View style={styles.empty}>
                        <Text
                            style={[
                                styles.greeting,
                                { color: theme.foreground },
                            ]}
                        >
                            What are we building?
                        </Text>
                        {active ? (
                            footer
                        ) : (
                            <Pressable
                                onPress={newDraft}
                                style={[
                                    styles.newSession,
                                    { backgroundColor: theme.primary },
                                ]}
                                accessibilityRole="button"
                            >
                                <Text
                                    style={{
                                        color: theme.primaryForeground,
                                        fontWeight: "600",
                                    }}
                                >
                                    New session
                                </Text>
                            </Pressable>
                        )}
                    </View>
                ) : (
                    <>
                        <MessageList
                            key={activeId ?? "empty"}
                            messages={messages}
                            approval={approval}
                            onRegenerate={() => {
                                if (activeId) {
                                    regenerateTurn(activeId);
                                }
                            }}
                        />
                        <View
                            style={{
                                paddingBottom: Math.max(insets.bottom, 8),
                            }}
                        >
                            {hasPanels ? (
                                <View style={styles.panels}>
                                    <CompactionBanner
                                        visible={progress?.compacting ?? false}
                                        summary={
                                            progress?.compactionSummary ?? ""
                                        }
                                    />
                                    <TodoProgressPanel
                                        todos={progress?.todos ?? null}
                                    />
                                    <BackgroundTasksPanel
                                        tasks={tasks}
                                        onCancel={(task) => {
                                            if (!activeSessionId) {
                                                return;
                                            }
                                            void cancelBackgroundTask(
                                                task.task_id,
                                                activeSessionId,
                                            ).catch((error: unknown) => {
                                                Alert.alert(
                                                    "Could not cancel task",
                                                    error instanceof Error
                                                        ? error.message
                                                        : String(error),
                                                );
                                            });
                                        }}
                                    />
                                </View>
                            ) : null}
                            {footer ? (
                                <View style={styles.banner}>{footer}</View>
                            ) : null}
                        </View>
                    </>
                )}
            </KeyboardAvoidingView>

            <ActionSheet
                visible={menuOpen}
                title="Conversation"
                items={[
                    {
                        label: "Share transcript",
                        onPress: () => {
                            void Share.share({
                                message: transcriptText(messages),
                            }).catch((error: unknown) => {
                                Alert.alert(
                                    "Could not share",
                                    error instanceof Error
                                        ? error.message
                                        : String(error),
                                );
                            });
                        },
                    },
                    {
                        label: "Copy transcript",
                        onPress: () => {
                            void Clipboard.setStringAsync(
                                transcriptText(messages),
                            );
                        },
                    },
                ]}
                onClose={() => setMenuOpen(false)}
            />

            <ActionSheet
                visible={attachOpen}
                title="Add attachment"
                items={[
                    {
                        label: "Photo library",
                        onPress: () => void addAttachment("library"),
                    },
                    {
                        label: "Camera",
                        onPress: () => void addAttachment("camera"),
                    },
                    {
                        label: "Text document",
                        onPress: () => void addAttachment("document"),
                    },
                    {
                        label: "Paste image",
                        onPress: () => void addAttachment("clipboard"),
                    },
                ]}
                onClose={() => setAttachOpen(false)}
            />

            <TabOverviewSheet
                visible={overviewOpen}
                tabs={tabs}
                activeId={activeId}
                onSelect={selectTab}
                onClose={handleClose}
                onNew={newDraft}
                onDismiss={() => setOverviewOpen(false)}
            />

            <PickerSheet
                visible={picker === "project"}
                title="Project"
                allowDefault
                defaultLabel="No project"
                selectedId={activeProjectId}
                items={projects.map((project) => ({
                    id: project.id,
                    label: project.name,
                    description: project.path ?? undefined,
                }))}
                onSelect={(projectId) => {
                    if (!active) {
                        return;
                    }
                    useChat.getState().setProjectId(active.id, projectId);
                    if (active.sessionId === null) {
                        useRoute.getState().setProjectId(projectId);
                    } else {
                        void useProjects
                            .getState()
                            .moveSession(active.sessionId, projectId);
                    }
                }}
                onClose={() => setPicker(null)}
            />

            <PickerSheet
                visible={picker === "model"}
                title="Model"
                allowDefault
                defaultLabel="Server default"
                selectedId={modelId}
                sections={modelSections}
                onSelect={(id) => {
                    const model = models.find((entry) => entry.id === id);
                    const nextEffort =
                        sessionEffort &&
                        model?.efforts.includes(sessionEffort)
                            ? sessionEffort
                            : null;
                    if (active?.sessionId) {
                        useChat
                            .getState()
                            .setModel(active.id, id);
                        useChat
                            .getState()
                            .setEffort(active.id, nextEffort);
                        if (model) {
                            void setSessionRoute(active.sessionId, {
                                provider: model.provider,
                                model: model.model,
                                reasoning_effort: nextEffort,
                            }).catch(() => {
                                // The session keeps its previous route.
                            });
                        }
                        return;
                    }
                    useRoute.getState().setModelId(id);
                    if (nextEffort === null && routeEffort !== null) {
                        useRoute.getState().setReasoningEffort(null);
                    }
                }}
                onClose={() => setPicker(null)}
            />

            <PickerSheet
                visible={picker === "effort"}
                title="Reasoning effort"
                allowDefault
                defaultLabel="Default"
                selectedId={activeEffort}
                items={efforts.map((effort) => ({
                    id: effort,
                    label: effort,
                }))}
                onSelect={(effort) => {
                    if (active?.sessionId && selectedModel) {
                        useChat.getState().setEffort(active.id, effort);
                        void setSessionRoute(active.sessionId, {
                            provider: selectedModel.provider,
                            model: selectedModel.model,
                            reasoning_effort: effort,
                        }).catch(() => {
                            // The session keeps its previous route.
                        });
                        return;
                    }
                    useRoute.getState().setReasoningEffort(effort);
                }}
                onClose={() => setPicker(null)}
            />

            {canPickAgent ? (
                <PickerSheet
                    visible={picker === "agent"}
                    title="Agent"
                    allowDefault
                    defaultLabel="Default agent"
                    selectedId={routeAgentKey}
                    items={agents
                        .filter(
                            (agent) =>
                                agent.mode === "primary" ||
                                agent.kind === "main",
                        )
                        .map((agent) => ({
                            id: agent.key,
                            label: agent.name || agent.key,
                            description: agent.description,
                        }))}
                    onSelect={(id) => useRoute.getState().setAgentKey(id)}
                    onClose={() => setPicker(null)}
                />
            ) : null}
        </View>
    );
}

const styles = StyleSheet.create({
    safe: { flex: 1 },
    flex: { flex: 1 },
    topBar: {
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 12,
        paddingTop: 4,
        paddingBottom: 4,
    },
    back: {
        width: 32,
        height: 32,
        alignItems: "center",
        justifyContent: "center",
    },
    topTitle: {
        flex: 1,
        fontSize: 14,
        fontWeight: "600",
    },
    more: {
        width: 32,
        height: 32,
        alignItems: "center",
        justifyContent: "center",
    },
    empty: {
        flex: 1,
        justifyContent: "center",
        paddingBottom: 24,
    },
    greeting: {
        fontSize: 30,
        lineHeight: 36,
        fontWeight: "600",
        textAlign: "center",
        paddingHorizontal: 24,
        marginBottom: 18,
    },
    banner: {
        paddingHorizontal: 12,
        paddingBottom: 8,
    },
    panels: {
        paddingHorizontal: 12,
        paddingTop: 6,
        gap: 6,
    },
    newSession: {
        alignSelf: "center",
        height: 44,
        borderRadius: 11,
        paddingHorizontal: 18,
        alignItems: "center",
        justifyContent: "center",
    },
});
