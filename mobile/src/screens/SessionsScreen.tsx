import Feather from "@expo/vector-icons/Feather";
import { useEffect, useMemo, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    FlatList,
    Platform,
    Pressable,
    RefreshControl,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import type {
    NovaProject,
    NovaSessionSummary,
} from "../api/types";
import { ActionSheet } from "../components/ActionSheet";
import { PickerSheet } from "../components/PickerSheet";
import { ProjectDialog } from "../components/ProjectDialog";
import { TextPromptDialog } from "../components/TextPromptDialog";
import { closeTab } from "../lib/tab-actions";
import { readExpandedProjects, writeExpandedProjects } from "../lib/storage";
import { useProjects } from "../state/projects";
import { useSessions } from "../state/sessions";
import { tabForSession } from "../state/tabs";
import { buildSessionRows, type Row } from "../sessions/rows";
import { useTheme } from "../theme/useTheme";

function relativeTime(ms: number): string {
    const delta = Date.now() - ms;
    if (!Number.isFinite(delta) || delta < 60_000) {
        return "just now";
    }
    const minutes = Math.floor(delta / 60_000);
    if (minutes < 60) {
        return `${minutes}m ago`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return `${hours}h ago`;
    }
    return `${Math.floor(hours / 24)}d ago`;
}

export function SessionsScreen({
    onOpen,
    onNew,
    onNewInProject,
    onSettings,
}: {
    onOpen: (session: NovaSessionSummary) => void;
    onNew: () => void;
    onNewInProject: (projectId: string) => void;
    onSettings: () => void;
}) {
    const { theme } = useTheme();
    const items = useSessions((state) => state.items);
    const loading = useSessions((state) => state.loading);
    const error = useSessions((state) => state.error);
    const refresh = useSessions((state) => state.refresh);
    const renameSession = useSessions((state) => state.rename);
    const setPinned = useSessions((state) => state.setPinned);
    const deleteRemote = useSessions((state) => state.deleteRemote);
    const projects = useProjects((state) => state.items);
    const projectsLoading = useProjects((state) => state.loading);
    const projectsError = useProjects((state) => state.error);
    const refreshProjects = useProjects((state) => state.refresh);
    const createProject = useProjects((state) => state.create);
    const renameProject = useProjects((state) => state.rename);
    const removeProject = useProjects((state) => state.remove);
    const moveSession = useProjects((state) => state.moveSession);

    const [query, setQuery] = useState("");
    const [expanded, setExpanded] = useState<Set<string>>(new Set());
    const [dialog, setDialog] = useState<{
        mode: "create" | "rename";
        project?: NovaProject;
    } | null>(null);
    const [moving, setMoving] = useState<NovaSessionSummary | null>(null);
    const [sessionAction, setSessionAction] =
        useState<NovaSessionSummary | null>(null);
    const [renameTarget, setRenameTarget] =
        useState<NovaSessionSummary | null>(null);

    useEffect(() => {
        if (items.length === 0) {
            void refresh();
        }
        if (projects.length === 0) {
            void refreshProjects();
        }
    }, [items.length, projects.length, refresh, refreshProjects]);

    useEffect(() => {
        let active = true;
        void readExpandedProjects().then((ids) => {
            if (active) {
                setExpanded(new Set(ids));
            }
        });
        return () => {
            active = false;
        };
    }, []);

    const persistExpanded = (next: Set<string>) => {
        void writeExpandedProjects([...next]);
    };

    const toggleProject = (projectId: string) => {
        setExpanded((previous) => {
            const next = new Set(previous);
            if (next.has(projectId)) {
                next.delete(projectId);
            } else {
                next.add(projectId);
            }
            persistExpanded(next);
            return next;
        });
    };

    const confirmDelete = (project: NovaProject) => {
        Alert.alert(
            "Delete project?",
            `"${project.name}" will be removed. Its sessions stay and become ungrouped.`,
            [
                { text: "Cancel", style: "cancel" },
                {
                    text: "Delete",
                    style: "destructive",
                    onPress: () => {
                        setExpanded((previous) => {
                            if (!previous.has(project.id)) {
                                return previous;
                            }
                            const next = new Set(previous);
                            next.delete(project.id);
                            persistExpanded(next);
                            return next;
                        });
                        void removeProject(project.id);
                    },
                },
            ],
        );
    };

    const showProjectActions = (project: NovaProject) => {
        const actions = [
            {
                text: "New chat",
                onPress: () => onNewInProject(project.id),
            },
            {
                text: "Rename",
                onPress: () => setDialog({ mode: "rename", project }),
            },
            {
                text: "Delete",
                style: "destructive" as const,
                onPress: () => confirmDelete(project),
            },
        ];
        if (Platform.OS === "ios") {
            Alert.alert(project.name, project.path ?? undefined, [
                ...actions,
                { text: "Cancel", style: "cancel" },
            ]);
            return;
        }
        Alert.alert(project.name, project.path ?? undefined, actions);
    };

    const showSessionActions = (session: NovaSessionSummary) => {
        setSessionAction(session);
    };

    const confirmDeleteSession = (session: NovaSessionSummary) => {
        Alert.alert(
            "Delete session?",
            `"${session.title ?? "Untitled session"}" and its messages will be removed.`,
            [
                { text: "Cancel", style: "cancel" },
                {
                    text: "Delete",
                    style: "destructive",
                    onPress: () => {
                        void deleteRemote(session.id)
                            .then(() => {
                                const tab = tabForSession(session.id);
                                if (tab) {
                                    closeTab(tab.id);
                                }
                            })
                            .catch((error: unknown) => {
                                Alert.alert(
                                    "Could not delete session",
                                    error instanceof Error
                                        ? error.message
                                        : String(error),
                                );
                            });
                    },
                },
            ],
        );
    };

    const rows = useMemo<Row[]>(
        () => buildSessionRows({ items, projects, expanded, query }),
        [items, projects, expanded, query],
    );

    const renderRow = ({ item }: { item: Row }) => {
        if (item.kind === "header") {
            return (
                <View style={styles.sectionHeader}>
                    <Text style={[styles.sectionTitle, { color: theme.weak }]}>
                        {item.title}
                    </Text>
                    {item.createProject ? (
                        <Pressable
                            onPress={() => setDialog({ mode: "create" })}
                            hitSlop={8}
                            style={styles.sectionAdd}
                            accessibilityRole="button"
                            accessibilityLabel="New project"
                        >
                            <Feather
                                name="plus"
                                size={15}
                                color={theme.weakStrong}
                            />
                        </Pressable>
                    ) : null}
                </View>
            );
        }

        if (item.kind === "project") {
            return (
                <Pressable
                    onPress={() => toggleProject(item.project.id)}
                    onLongPress={() => showProjectActions(item.project)}
                    style={[styles.projectRow, { borderColor: theme.border }]}
                    accessibilityRole="button"
                    accessibilityState={{ expanded: item.expanded }}
                >
                    <Feather
                        name={item.expanded ? "chevron-down" : "chevron-right"}
                        size={15}
                        color={theme.weak}
                    />
                    <Feather name="folder" size={15} color={theme.brand} />
                    <View style={styles.projectBody}>
                        <Text
                            numberOfLines={1}
                            style={[
                                styles.projectName,
                                { color: theme.foreground },
                            ]}
                        >
                            {item.project.name}
                        </Text>
                        <Text
                            numberOfLines={1}
                            style={[styles.projectPath, { color: theme.weak }]}
                        >
                            {item.project.path ?? "No workspace path"} ·{" "}
                            {item.count}{" "}
                            {item.count === 1 ? "chat" : "chats"}
                        </Text>
                    </View>
                    <Pressable
                        onPress={(event) => {
                            event.stopPropagation();
                            showProjectActions(item.project);
                        }}
                        hitSlop={8}
                        accessibilityRole="button"
                        accessibilityLabel={`Actions for ${item.project.name}`}
                    >
                        <Feather
                            name="more-horizontal"
                            size={17}
                            color={theme.weak}
                        />
                    </Pressable>
                </Pressable>
            );
        }

        if (item.kind === "project-empty") {
            return (
                <View style={styles.projectEmpty}>
                    <Text style={[styles.projectEmptyText, { color: theme.weak }]}>
                        No conversations in this project yet.
                    </Text>
                    <Pressable
                        onPress={() => onNewInProject(item.project.id)}
                        style={[
                            styles.inlineButton,
                            { borderColor: theme.border },
                        ]}
                    >
                        <Feather name="plus" size={12} color={theme.brand} />
                        <Text
                            style={[
                                styles.inlineButtonText,
                                { color: theme.brand },
                            ]}
                        >
                            New chat
                        </Text>
                    </Pressable>
                </View>
            );
        }

        if (item.kind === "empty") {
            return (
                <View style={styles.empty}>
                    <Text style={[styles.emptyTitle, { color: theme.foreground }]}>
                        {item.title}
                    </Text>
                    <Text style={[styles.emptyBody, { color: theme.weakStrong }]}>
                        {item.body}
                    </Text>
                </View>
            );
        }

        const session = item.session;
        return (
            <Pressable
                onPress={() => onOpen(session)}
                onLongPress={() => showSessionActions(session)}
                style={[
                    styles.row,
                    {
                        borderBottomColor: theme.border,
                        paddingLeft: item.indented ? 28 : 0,
                    },
                ]}
                accessibilityRole="button"
            >
                <View style={styles.rowBody}>
                    <View style={styles.rowTitleLine}>
                        {session.pinned ? (
                            <Feather
                                name="bookmark"
                                size={12}
                                color={theme.weak}
                            />
                        ) : null}
                        <Text
                            numberOfLines={1}
                            style={[
                                styles.rowTitle,
                                { color: theme.foreground },
                            ]}
                        >
                            {session.title?.trim() || "Untitled session"}
                        </Text>
                    </View>
                    <Text style={[styles.rowMeta, { color: theme.weak }]}>
                        {relativeTime(session.updated_at)}
                    </Text>
                </View>
                <Feather name="chevron-right" size={16} color={theme.weak} />
            </Pressable>
        );
    };

    const busy = loading || projectsLoading;
    const shownError = error ?? projectsError;

    return (
        <SafeAreaView
            style={[styles.safe, { backgroundColor: theme.background }]}
            edges={["top", "left", "right", "bottom"]}
        >
            <View style={styles.header}>
                <Text style={[styles.title, { color: theme.foreground }]}>
                    Nova
                </Text>
                <View style={styles.headerActions}>
                    <Pressable
                        onPress={onSettings}
                        style={styles.iconButton}
                        accessibilityRole="button"
                        accessibilityLabel="Settings"
                    >
                        <Feather
                            name="settings"
                            size={18}
                            color={theme.weakStrong}
                        />
                    </Pressable>
                    <Pressable
                        onPress={onNew}
                        style={[
                            styles.newButton,
                            { backgroundColor: theme.primary },
                        ]}
                        accessibilityRole="button"
                    >
                        <Feather
                            name="plus"
                            size={15}
                            color={theme.primaryForeground}
                        />
                        <Text
                            style={[
                                styles.newText,
                                { color: theme.primaryForeground },
                            ]}
                        >
                            New
                        </Text>
                    </Pressable>
                </View>
            </View>

            <View
                style={[
                    styles.search,
                    {
                        backgroundColor: theme.muted,
                        borderColor: theme.border,
                    },
                ]}
            >
                <Feather name="search" size={15} color={theme.weak} />
                <TextInput
                    value={query}
                    onChangeText={setQuery}
                    placeholder="Search conversations"
                    placeholderTextColor={theme.weak}
                    style={[styles.searchInput, { color: theme.foreground }]}
                    autoCapitalize="none"
                    autoCorrect={false}
                    returnKeyType="search"
                    accessibilityLabel="Search conversations"
                />
                {query ? (
                    <Pressable
                        onPress={() => setQuery("")}
                        hitSlop={8}
                        accessibilityRole="button"
                        accessibilityLabel="Clear search"
                    >
                        <Feather name="x" size={14} color={theme.weak} />
                    </Pressable>
                ) : null}
            </View>

            {shownError ? (
                <View
                    style={[
                        styles.error,
                        {
                            backgroundColor: theme.dangerSoft,
                            borderColor: theme.danger,
                        },
                    ]}
                >
                    <Text style={{ color: theme.danger }}>{shownError}</Text>
                </View>
            ) : null}

            <FlatList
                data={rows}
                keyExtractor={(item) => item.key}
                renderItem={renderRow}
                contentContainerStyle={styles.list}
                refreshControl={
                    <RefreshControl
                        refreshing={busy}
                        onRefresh={() => {
                            void Promise.all([refresh(), refreshProjects()]);
                        }}
                        tintColor={theme.weak}
                    />
                }
                ListEmptyComponent={
                    busy ? (
                        <ActivityIndicator
                            style={styles.emptySpinner}
                            color={theme.weak}
                        />
                    ) : undefined
                }
            />

            <ProjectDialog
                visible={dialog !== null}
                mode={dialog?.mode ?? "create"}
                initialName={dialog?.project?.name ?? ""}
                initialPath={dialog?.project?.path ?? ""}
                onSubmit={(name, path) => {
                    if (dialog?.mode === "rename" && dialog.project) {
                        void renameProject(dialog.project.id, name, path);
                        setDialog(null);
                        return;
                    }
                    void createProject(name, path).then((project) => {
                        if (!project) {
                            return;
                        }
                        setExpanded((previous) => {
                            const next = new Set(previous);
                            next.add(project.id);
                            persistExpanded(next);
                            return next;
                        });
                        setDialog(null);
                    });
                }}
                onClose={() => setDialog(null)}
            />

            <ActionSheet
                visible={sessionAction !== null}
                title={sessionAction?.title ?? "Session"}
                items={
                    sessionAction
                        ? [
                              {
                                  label: "Rename",
                                  onPress: () =>
                                      setRenameTarget(sessionAction),
                              },
                              {
                                  label: sessionAction.pinned
                                      ? "Unpin"
                                      : "Pin",
                                  onPress: () => {
                                      void setPinned(
                                          sessionAction.id,
                                          !sessionAction.pinned,
                                      ).catch((error: unknown) => {
                                          Alert.alert(
                                              "Could not update pin",
                                              error instanceof Error
                                                  ? error.message
                                                  : String(error),
                                          );
                                      });
                                  },
                              },
                              {
                                  label: "Move to project",
                                  onPress: () => setMoving(sessionAction),
                              },
                              {
                                  label: "Delete",
                                  destructive: true,
                                  onPress: () =>
                                      confirmDeleteSession(sessionAction),
                              },
                          ]
                        : []
                }
                onClose={() => setSessionAction(null)}
            />

            <TextPromptDialog
                visible={renameTarget !== null}
                title="Rename session"
                initialValue={renameTarget?.title ?? ""}
                placeholder="Session title"
                submitLabel="Save"
                onSubmit={(title) => {
                    if (renameTarget) {
                        void renameSession(renameTarget.id, title).catch(
                            (error: unknown) => {
                                Alert.alert(
                                    "Could not rename session",
                                    error instanceof Error
                                        ? error.message
                                        : String(error),
                                );
                            },
                        );
                    }
                    setRenameTarget(null);
                }}
                onClose={() => setRenameTarget(null)}
            />

            <PickerSheet
                visible={moving !== null}
                title="Move to project"
                items={projects.map((project) => ({
                    id: project.id,
                    label: project.name,
                    description: project.path ?? undefined,
                }))}
                selectedId={moving?.project_id ?? null}
                allowDefault
                defaultLabel="No project"
                onSelect={(projectId) => {
                    if (moving) {
                        void moveSession(moving.id, projectId);
                    }
                }}
                onClose={() => setMoving(null)}
            />
        </SafeAreaView>
    );
}

const styles = StyleSheet.create({
    safe: { flex: 1 },
    search: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        marginHorizontal: 16,
        marginBottom: 8,
        height: 38,
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 10,
    },
    searchInput: {
        flex: 1,
        fontSize: 14,
        padding: 0,
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: 20,
        paddingTop: 8,
        paddingBottom: 12,
    },
    title: {
        fontSize: 26,
        fontWeight: "700",
    },
    headerActions: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
    },
    iconButton: {
        width: 36,
        height: 36,
        alignItems: "center",
        justifyContent: "center",
    },
    newButton: {
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        height: 36,
        borderRadius: 10,
        paddingHorizontal: 12,
    },
    newText: {
        fontSize: 13,
        fontWeight: "600",
    },
    error: {
        marginHorizontal: 20,
        marginBottom: 8,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 10,
    },
    list: {
        paddingHorizontal: 20,
        paddingBottom: 24,
        flexGrow: 1,
    },
    sectionHeader: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingTop: 16,
        paddingBottom: 6,
    },
    sectionTitle: {
        fontSize: 11.5,
        fontWeight: "700",
        letterSpacing: 0.4,
        textTransform: "uppercase",
    },
    sectionAdd: {
        width: 26,
        height: 26,
        alignItems: "center",
        justifyContent: "center",
    },
    projectRow: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingVertical: 11,
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    projectBody: {
        flex: 1,
        gap: 2,
    },
    projectName: {
        fontSize: 14.5,
        fontWeight: "600",
    },
    projectPath: {
        fontSize: 11.5,
    },
    projectEmpty: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        paddingLeft: 28,
        paddingVertical: 10,
    },
    projectEmptyText: {
        flex: 1,
        fontSize: 12.5,
    },
    inlineButton: {
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 8,
        paddingVertical: 5,
    },
    inlineButtonText: {
        fontSize: 12,
        fontWeight: "600",
    },
    row: {
        flexDirection: "row",
        alignItems: "center",
        gap: 12,
        paddingVertical: 14,
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    rowBody: {
        flex: 1,
        gap: 3,
    },
    rowTitleLine: {
        flexDirection: "row",
        alignItems: "center",
        gap: 5,
    },
    rowTitle: {
        flexShrink: 1,
        fontSize: 15,
        fontWeight: "500",
    },
    rowMeta: {
        fontSize: 12,
    },
    empty: {
        paddingTop: 44,
        gap: 8,
        alignItems: "center",
    },
    emptyTitle: {
        fontSize: 17,
        fontWeight: "600",
    },
    emptyBody: {
        maxWidth: 300,
        textAlign: "center",
        fontSize: 13.5,
        lineHeight: 20,
    },
    emptySpinner: {
        marginTop: 72,
    },
});
