import Feather from "@expo/vector-icons/Feather";
import { useEffect, useRef, type ComponentRef } from "react";
import {
    ActivityIndicator,
    Alert,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { useChat } from "../state/chat";
import type { SessionTab } from "../tabs/tab-state";
import { useTheme } from "../theme/useTheme";

function TabChip({
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

    const marker =
        tab.attention === "approval"
            ? "!"
            : tab.attention === "question"
              ? "?"
              : null;

    const confirmClose = () => {
        Alert.alert("Close tab", `Close "${tab.title}"?`, [
            { text: "Cancel", style: "cancel" },
            { text: "Close", style: "destructive", onPress: onClose },
        ]);
    };

    return (
        <Pressable
            onPress={onSelect}
            onLongPress={confirmClose}
            style={[
                styles.chip,
                {
                    backgroundColor: active ? theme.brandSoft : theme.card,
                    borderColor: active ? theme.brand : theme.border,
                },
            ]}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={tab.title}
        >
            {streaming ? (
                <ActivityIndicator size="small" color={theme.brand} />
            ) : marker ? (
                <Text
                    style={[
                        styles.marker,
                        { color: theme.warning },
                    ]}
                >
                    {marker}
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
            ) : null}
            <Text
                numberOfLines={1}
                style={[
                    styles.chipText,
                    {
                        color: active ? theme.brand : theme.weakStrong,
                        fontWeight: active ? "600" : "500",
                    },
                ]}
            >
                {tab.title}
            </Text>
            {active ? (
                <Pressable
                    onPress={(event) => {
                        event.stopPropagation();
                        onClose();
                    }}
                    hitSlop={8}
                    style={styles.close}
                    accessibilityRole="button"
                    accessibilityLabel={`Close ${tab.title}`}
                >
                    <Feather name="x" size={12} color={theme.weak} />
                </Pressable>
            ) : null}
        </Pressable>
    );
}

export function TabStrip({
    tabs,
    activeId,
    onSelect,
    onClose,
    onNew,
    onOverview,
}: {
    tabs: SessionTab[];
    activeId: string | null;
    onSelect: (id: string) => void;
    onClose: (id: string) => void;
    onNew: () => void;
    onOverview: () => void;
}) {
    const { theme } = useTheme();
    const scrollRef = useRef<ComponentRef<typeof ScrollView>>(null);
    const active = tabs.find((tab) => tab.id === activeId);

    useEffect(() => {
        const index = tabs.findIndex((tab) => tab.id === activeId);
        if (index >= 0) {
            scrollRef.current?.scrollTo({
                x: Math.max(0, index * 132 - 40),
                animated: true,
            });
        }
    }, [activeId, tabs.length]);

    if (tabs.length === 0) {
        return null;
    }

    const pending = tabs.filter(
        (tab) => tab.attention !== null || tab.unread !== null,
    ).length;

    return (
        <View
            style={[
                styles.bar,
                {
                    borderBottomColor: theme.border,
                    backgroundColor: theme.background,
                },
            ]}
        >
            <ScrollView
                ref={scrollRef}
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.content}
                style={styles.strip}
            >
                {tabs.map((tab) => (
                    <TabChip
                        key={tab.id}
                        tab={tab}
                        active={tab.id === activeId}
                        onSelect={() => onSelect(tab.id)}
                        onClose={() => onClose(tab.id)}
                    />
                ))}
                {active?.sessionId !== null ? (
                    <Pressable
                        onPress={onNew}
                        style={[
                            styles.add,
                            {
                                borderColor: theme.border,
                                backgroundColor: theme.card,
                            },
                        ]}
                        accessibilityRole="button"
                        accessibilityLabel="New tab"
                    >
                        <Feather name="plus" size={14} color={theme.weakStrong} />
                    </Pressable>
                ) : null}
            </ScrollView>
            <Pressable
                onPress={onOverview}
                style={styles.overview}
                accessibilityRole="button"
                accessibilityLabel="All tabs"
            >
                <Feather name="list" size={16} color={theme.weakStrong} />
                {pending > 0 ? (
                    <View
                        style={[
                            styles.badge,
                            { backgroundColor: theme.warning },
                        ]}
                    >
                        <Text style={styles.badgeText}>{pending}</Text>
                    </View>
                ) : null}
            </Pressable>
        </View>
    );
}

const styles = StyleSheet.create({
    bar: {
        flexDirection: "row",
        alignItems: "center",
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    strip: {
        flex: 1,
    },
    overview: {
        width: 40,
        height: 36,
        alignItems: "center",
        justifyContent: "center",
    },
    badge: {
        position: "absolute",
        top: 4,
        right: 4,
        minWidth: 14,
        height: 14,
        borderRadius: 7,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 3,
    },
    badgeText: {
        color: "#FFFFFF",
        fontSize: 9,
        fontWeight: "700",
    },
    content: {
        paddingHorizontal: 10,
        paddingVertical: 8,
        gap: 6,
        alignItems: "center",
    },
    chip: {
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        minWidth: 84,
        maxWidth: 168,
        height: 32,
        paddingHorizontal: 10,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
    },
    chipText: {
        flexShrink: 1,
        fontSize: 12.5,
    },
    dot: {
        width: 6,
        height: 6,
        borderRadius: 3,
    },
    marker: {
        fontSize: 12,
        fontWeight: "700",
    },
    close: {
        marginLeft: 2,
    },
    add: {
        width: 32,
        height: 32,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
    },
});
