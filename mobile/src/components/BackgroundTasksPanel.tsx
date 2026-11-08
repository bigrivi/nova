import Feather from "@expo/vector-icons/Feather";
import { memo, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import type { NovaBackgroundTask } from "../api/types";
import { useTheme } from "../theme/useTheme";

const LIVE = new Set(["queued", "running"]);

function statusColor(
    status: string,
    theme: ReturnType<typeof useTheme>["theme"],
): string {
    if (status === "failed" || status === "timed_out") {
        return theme.danger;
    }
    if (status === "succeeded") {
        return theme.success;
    }
    if (status === "cancelled" || status === "interrupted") {
        return theme.weak;
    }
    return theme.brand;
}

function TaskRow({
    task,
    onCancel,
}: {
    task: NovaBackgroundTask;
    onCancel: (task: NovaBackgroundTask) => void;
}) {
    const { theme } = useTheme();
    const [open, setOpen] = useState(false);
    const live = LIVE.has(task.status);
    const detail =
        task.output_tail?.trim() ||
        task.result?.trim() ||
        task.error?.trim() ||
        "";
    const color = statusColor(task.status, theme);

    return (
        <View style={[styles.row, { borderTopColor: theme.border }]}>
            <Pressable
                onPress={() => setOpen((value) => !value)}
                style={styles.rowHeader}
                accessibilityRole="button"
                accessibilityState={{ expanded: open }}
            >
                {live ? (
                    <ActivityIndicator size="small" color={color} />
                ) : (
                    <Feather
                        name={
                            task.status === "succeeded"
                                ? "check-circle"
                                : task.status === "cancelled"
                                  ? "slash"
                                  : "alert-circle"
                        }
                        size={14}
                        color={color}
                    />
                )}
                <View style={styles.rowBody}>
                    <Text
                        numberOfLines={1}
                        style={[styles.label, { color: theme.foreground }]}
                    >
                        {task.label || task.kind}
                    </Text>
                    <Text style={[styles.meta, { color }]}>
                        {task.status}
                        {task.progress != null
                            ? ` · ${Math.round(task.progress * 100)}%`
                            : ""}
                        {task.progress_message
                            ? ` · ${task.progress_message}`
                            : ""}
                    </Text>
                </View>
                {live ? (
                    <Pressable
                        onPress={(event) => {
                            event.stopPropagation();
                            onCancel(task);
                        }}
                        hitSlop={8}
                        style={[
                            styles.cancel,
                            { borderColor: theme.border },
                        ]}
                        accessibilityRole="button"
                        accessibilityLabel={`Cancel ${task.label}`}
                    >
                        <Text style={[styles.cancelText, { color: theme.danger }]}>
                            Cancel
                        </Text>
                    </Pressable>
                ) : null}
                <Feather
                    name={open ? "chevron-down" : "chevron-right"}
                    size={14}
                    color={theme.weak}
                />
            </Pressable>
            {open ? (
                <ScrollView style={styles.detailBox}>
                    <Text
                        selectable
                        style={[styles.detail, { color: theme.weakStrong }]}
                    >
                        {detail || "No output retained."}
                    </Text>
                    {task.output_truncated ? (
                        <Text style={[styles.truncated, { color: theme.weak }]}>
                            Output was truncated by the server.
                        </Text>
                    ) : null}
                </ScrollView>
            ) : null}
        </View>
    );
}

export const BackgroundTasksPanel = memo(function BackgroundTasksPanel({
    tasks,
    onCancel,
}: {
    tasks: NovaBackgroundTask[];
    onCancel: (task: NovaBackgroundTask) => void;
}) {
    const { theme } = useTheme();
    const [open, setOpen] = useState(true);

    if (tasks.length === 0) {
        return null;
    }
    const live = tasks.filter((task) => LIVE.has(task.status)).length;

    return (
        <View
            style={[
                styles.card,
                { backgroundColor: theme.card, borderColor: theme.border },
            ]}
        >
            <Pressable
                onPress={() => setOpen((value) => !value)}
                style={styles.header}
                accessibilityRole="button"
                accessibilityState={{ expanded: open }}
            >
                <Feather
                    name="layers"
                    size={14}
                    color={live > 0 ? theme.brand : theme.weak}
                />
                <Text style={[styles.title, { color: theme.foreground }]}>
                    Background tasks
                </Text>
                <Text style={[styles.count, { color: theme.weak }]}>
                    {live > 0 ? `${live} running` : `${tasks.length} total`}
                </Text>
                <Feather
                    name={open ? "chevron-down" : "chevron-right"}
                    size={15}
                    color={theme.weak}
                />
            </Pressable>
            {open ? (
                <ScrollView style={styles.list}>
                    {tasks.map((task) => (
                        <TaskRow
                            key={task.task_id}
                            task={task}
                            onCancel={onCancel}
                        />
                    ))}
                </ScrollView>
            ) : null}
        </View>
    );
});

const styles = StyleSheet.create({
    card: {
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        overflow: "hidden",
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
        paddingHorizontal: 12,
        paddingVertical: 9,
    },
    title: {
        flex: 1,
        fontSize: 12.5,
        fontWeight: "600",
    },
    count: {
        fontSize: 11,
    },
    list: {
        maxHeight: 260,
    },
    row: {
        borderTopWidth: StyleSheet.hairlineWidth,
    },
    rowHeader: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: 12,
        paddingVertical: 9,
    },
    rowBody: {
        flex: 1,
        gap: 2,
    },
    label: {
        fontSize: 12.5,
        fontWeight: "500",
    },
    meta: {
        fontSize: 11,
    },
    cancel: {
        borderRadius: 6,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 7,
        paddingVertical: 3,
    },
    cancelText: {
        fontSize: 11,
        fontWeight: "600",
    },
    detailBox: {
        maxHeight: 200,
        paddingHorizontal: 12,
        paddingBottom: 10,
    },
    detail: {
        fontFamily: "monospace",
        fontSize: 11,
        lineHeight: 16,
    },
    truncated: {
        marginTop: 4,
        fontSize: 10.5,
    },
});
