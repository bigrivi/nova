import Feather from "@expo/vector-icons/Feather";
import {
    ActivityIndicator,
    Modal,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useChat } from "../state/chat";
import type { SessionTab } from "../tabs/tab-state";
import { useTheme } from "../theme/useTheme";

function TabRow({
    tab,
    active,
    onSelect,
    onClose,
}: {
    tab: SessionTab;
    active: boolean;
    onSelect: () => void;
    onClose: () => void;
}) {
    const { theme } = useTheme();
    const streaming = useChat(
        (state) => state.byId[tab.id]?.streaming ?? false,
    );

    return (
        <Pressable
            onPress={onSelect}
            style={[styles.row, { borderBottomColor: theme.border }]}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
        >
            <View style={styles.status}>
                {streaming ? (
                    <ActivityIndicator size="small" color={theme.brand} />
                ) : tab.attention ? (
                    <Text style={[styles.marker, { color: theme.warning }]}>
                        {tab.attention === "approval" ? "!" : "?"}
                    </Text>
                ) : tab.unread ? (
                    <View
                        style={[
                            styles.dot,
                            {
                                backgroundColor:
                                    tab.unread === "error"
                                        ? theme.danger
                                        : theme.brand,
                            },
                        ]}
                    />
                ) : (
                    <View
                        style={[styles.dot, { backgroundColor: theme.border }]}
                    />
                )}
            </View>
            <Text
                numberOfLines={1}
                style={[
                    styles.title,
                    {
                        color: active ? theme.brand : theme.foreground,
                    },
                ]}
            >
                {tab.title}
            </Text>
            <Pressable
                onPress={(event) => {
                    event.stopPropagation();
                    onClose();
                }}
                hitSlop={10}
                accessibilityRole="button"
                accessibilityLabel={`Close ${tab.title}`}
            >
                <Feather name="x" size={15} color={theme.weak} />
            </Pressable>
        </Pressable>
    );
}

export function TabOverviewSheet({
    visible,
    tabs,
    activeId,
    onSelect,
    onClose,
    onNew,
    onDismiss,
}: {
    visible: boolean;
    tabs: SessionTab[];
    activeId: string | null;
    onSelect: (id: string) => void;
    onClose: (id: string) => void;
    onNew: () => void;
    onDismiss: () => void;
}) {
    const { theme } = useTheme();
    const insets = useSafeAreaInsets();

    return (
        <Modal
            visible={visible}
            transparent
            animationType="slide"
            onRequestClose={onDismiss}
        >
            <View style={styles.root}>
                <Pressable
                    style={styles.backdrop}
                    onPress={onDismiss}
                    accessibilityLabel="Close tabs"
                />
                <View
                    style={[
                        styles.sheet,
                        {
                            backgroundColor: theme.card,
                            borderColor: theme.border,
                            paddingBottom: Math.max(insets.bottom, 16),
                        },
                    ]}
                >
                    <View style={styles.header}>
                        <Text style={[styles.heading, { color: theme.foreground }]}>
                            Open tabs
                        </Text>
                        <Pressable
                            onPress={onDismiss}
                            hitSlop={8}
                            accessibilityRole="button"
                            accessibilityLabel="Close"
                        >
                            <Feather name="x" size={18} color={theme.weak} />
                        </Pressable>
                    </View>

                    <ScrollView style={styles.list}>
                        {tabs.map((tab) => (
                            <TabRow
                                key={tab.id}
                                tab={tab}
                                active={tab.id === activeId}
                                onSelect={() => {
                                    onSelect(tab.id);
                                    onDismiss();
                                }}
                                onClose={() => onClose(tab.id)}
                            />
                        ))}
                        <Pressable
                            onPress={() => {
                                onNew();
                                onDismiss();
                            }}
                            style={styles.newRow}
                        >
                            <Feather name="plus" size={15} color={theme.brand} />
                            <Text style={[styles.newText, { color: theme.brand }]}>
                                New tab
                            </Text>
                        </Pressable>
                    </ScrollView>
                </View>
            </View>
        </Modal>
    );
}

const styles = StyleSheet.create({
    root: {
        flex: 1,
        justifyContent: "flex-end",
    },
    backdrop: {
        ...StyleSheet.absoluteFill,
        backgroundColor: "rgba(0,0,0,0.35)",
    },
    sheet: {
        maxHeight: "70%",
        borderTopLeftRadius: 16,
        borderTopRightRadius: 16,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 16,
        paddingTop: 14,
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 8,
    },
    heading: {
        fontSize: 16,
        fontWeight: "700",
    },
    list: {
        flexGrow: 0,
    },
    row: {
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        paddingVertical: 13,
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    status: {
        width: 18,
        alignItems: "center",
        justifyContent: "center",
    },
    dot: {
        width: 7,
        height: 7,
        borderRadius: 4,
    },
    marker: {
        fontSize: 12,
        fontWeight: "700",
    },
    title: {
        flex: 1,
        fontSize: 14,
        fontWeight: "500",
    },
    newRow: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingVertical: 14,
    },
    newText: {
        fontSize: 13.5,
        fontWeight: "600",
    },
});
