import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";

import type { TodoItem, TodoStatus } from "../chat/todo";
import { useTheme } from "../theme/useTheme";

function StatusIcon({ status }: { status: TodoStatus }) {
    const { theme } = useTheme();
    if (status === "in_progress") {
        return <ActivityIndicator size="small" color={theme.brand} />;
    }
    if (status === "completed") {
        return <Feather name="check-circle" size={15} color={theme.success} />;
    }
    if (status === "cancelled") {
        return <Feather name="x-circle" size={15} color={theme.weak} />;
    }
    return <Feather name="circle" size={15} color={theme.weak} />;
}

export function TodoProgressPanel({ todos }: { todos: TodoItem[] | null }) {
    const { theme } = useTheme();
    const [userOpen, setUserOpen] = useState<boolean | null>(null);

    if (!todos || todos.length === 0) {
        return null;
    }

    const total = todos.length;
    const completed = todos.filter((item) => item.status === "completed").length;
    const cancelled = todos.filter((item) => item.status === "cancelled").length;
    const inProgress = todos.find((item) => item.status === "in_progress");
    const lastCompleted = [...todos]
        .reverse()
        .find((item) => item.status === "completed");
    const allDone = total > 0 && completed + cancelled === total;
    const open = userOpen ?? Boolean(inProgress);
    const summary =
        inProgress?.content ??
        lastCompleted?.content ??
        "Tasks";

    return (
        <View
            style={[
                styles.card,
                { backgroundColor: theme.card, borderColor: theme.border },
            ]}
        >
            <Pressable
                onPress={() => setUserOpen(!open)}
                style={styles.header}
                accessibilityRole="button"
                accessibilityState={{ expanded: open }}
            >
                {inProgress && !allDone ? (
                    <ActivityIndicator size="small" color={theme.brand} />
                ) : allDone ? (
                    <Feather
                        name="check-circle"
                        size={15}
                        color={theme.success}
                    />
                ) : (
                    <Feather name="circle" size={15} color={theme.weak} />
                )}
                <Text
                    numberOfLines={1}
                    style={[styles.summary, { color: theme.foreground }]}
                >
                    {summary}
                </Text>
                <Text
                    style={[
                        styles.count,
                        {
                            backgroundColor: allDone
                                ? theme.successSoft
                                : theme.muted,
                            color: allDone
                                ? theme.successStrong
                                : theme.weakStrong,
                        },
                    ]}
                >
                    {completed}/{total}
                </Text>
                <Feather
                    name={open ? "chevron-down" : "chevron-right"}
                    size={15}
                    color={theme.weak}
                />
            </Pressable>

            {open ? (
                <View
                    style={[
                        styles.body,
                        {
                            borderTopColor: theme.border,
                            backgroundColor: theme.muted,
                        },
                    ]}
                >
                    {todos.map((todo, index) => (
                        <View key={`${todo.content}-${index}`} style={styles.row}>
                            <StatusIcon status={todo.status} />
                            <Text
                                style={[
                                    styles.rowText,
                                    {
                                        color:
                                            todo.status === "cancelled"
                                                ? theme.weak
                                                : theme.foreground,
                                        fontWeight:
                                            todo.status === "in_progress"
                                                ? "600"
                                                : "400",
                                        textDecorationLine:
                                            todo.status === "cancelled"
                                                ? "line-through"
                                                : "none",
                                    },
                                ]}
                            >
                                {todo.content}
                            </Text>
                        </View>
                    ))}
                </View>
            ) : null}
        </View>
    );
}

const styles = StyleSheet.create({
    card: {
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        overflow: "hidden",
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: 12,
        paddingVertical: 9,
    },
    summary: {
        flex: 1,
        fontSize: 13,
    },
    count: {
        borderRadius: 999,
        paddingHorizontal: 7,
        paddingVertical: 2,
        fontSize: 10.5,
        fontWeight: "700",
        overflow: "hidden",
    },
    body: {
        borderTopWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 12,
        paddingVertical: 8,
        gap: 7,
    },
    row: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
    },
    rowText: {
        flex: 1,
        fontSize: 12.5,
        lineHeight: 18,
    },
});
