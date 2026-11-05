import Feather from "@expo/vector-icons/Feather";
import {
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useConnection } from "../state/connection";
import { useTheme } from "../theme/useTheme";

export function SettingsScreen({ onBack }: { onBack: () => void }) {
    const { theme, name } = useTheme();
    const baseUrl = useConnection((state) => state.baseUrl);
    const username = useConnection((state) => state.username);
    const disconnect = useConnection((state) => state.disconnect);

    return (
        <SafeAreaView
            style={[styles.safe, { backgroundColor: theme.background }]}
            edges={["top", "left", "right", "bottom"]}
        >
            <View style={styles.header}>
                <Pressable
                    onPress={onBack}
                    style={styles.back}
                    accessibilityRole="button"
                    accessibilityLabel="Back"
                >
                    <Feather
                        name="chevron-left"
                        size={22}
                        color={theme.foreground}
                    />
                </Pressable>
                <Text style={[styles.title, { color: theme.foreground }]}>
                    Settings
                </Text>
            </View>

            <ScrollView contentContainerStyle={styles.content}>
                <View
                    style={[
                        styles.card,
                        {
                            backgroundColor: theme.card,
                            borderColor: theme.border,
                        },
                    ]}
                >
                    <Row label="Server" value={baseUrl} theme={theme} />
                    <Row
                        label="Account"
                        value={username || "No credentials"}
                        theme={theme}
                    />
                    <Row label="Theme" value={name} theme={theme} />
                </View>

                <Pressable
                    onPress={() => void disconnect()}
                    style={[
                        styles.danger,
                        { borderColor: theme.danger },
                    ]}
                    accessibilityRole="button"
                >
                    <Text style={{ color: theme.danger, fontWeight: "600" }}>
                        Disconnect
                    </Text>
                </Pressable>

                <Text style={[styles.note, { color: theme.weak }]}>
                    Conversations, memories and files stay on the Nova server.
                    This app only renders them.
                </Text>
            </ScrollView>
        </SafeAreaView>
    );
}

function Row({
    label,
    value,
    theme,
}: {
    label: string;
    value: string;
    theme: ReturnType<typeof useTheme>["theme"];
}) {
    return (
        <View style={[styles.row, { borderBottomColor: theme.border }]}>
            <Text style={[styles.rowLabel, { color: theme.weakStrong }]}>
                {label}
            </Text>
            <Text
                numberOfLines={1}
                style={[styles.rowValue, { color: theme.foreground }]}
            >
                {value}
            </Text>
        </View>
    );
}

const styles = StyleSheet.create({
    safe: { flex: 1 },
    header: {
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        paddingHorizontal: 12,
        paddingTop: 4,
        paddingBottom: 8,
    },
    back: {
        width: 32,
        height: 32,
        alignItems: "center",
        justifyContent: "center",
    },
    title: {
        fontSize: 20,
        fontWeight: "700",
    },
    content: {
        padding: 20,
        gap: 16,
    },
    card: {
        borderRadius: 12,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 14,
    },
    row: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        paddingVertical: 13,
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    rowLabel: {
        fontSize: 13,
    },
    rowValue: {
        flexShrink: 1,
        fontSize: 13,
        fontWeight: "500",
    },
    danger: {
        height: 46,
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
    },
    note: {
        fontSize: 12,
        lineHeight: 18,
    },
});
