import Feather from "@expo/vector-icons/Feather";
import {
    Modal,
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "../theme/useTheme";

export type ActionItem = {
    label: string;
    destructive?: boolean;
    onPress: () => void;
};

export function ActionSheet({
    visible,
    title,
    items,
    onClose,
}: {
    visible: boolean;
    title: string;
    items: ActionItem[];
    onClose: () => void;
}) {
    const { theme } = useTheme();
    const insets = useSafeAreaInsets();

    return (
        <Modal
            visible={visible}
            transparent
            animationType="slide"
            onRequestClose={onClose}
        >
            <View style={styles.root}>
                <Pressable
                    style={styles.backdrop}
                    onPress={onClose}
                    accessibilityLabel="Close actions"
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
                        <Text
                            numberOfLines={1}
                            style={[styles.title, { color: theme.foreground }]}
                        >
                            {title}
                        </Text>
                        <Pressable
                            onPress={onClose}
                            hitSlop={8}
                            accessibilityRole="button"
                            accessibilityLabel="Close"
                        >
                            <Feather name="x" size={18} color={theme.weak} />
                        </Pressable>
                    </View>
                    {items.map((item) => (
                        <Pressable
                            key={item.label}
                            onPress={() => {
                                onClose();
                                item.onPress();
                            }}
                            style={[styles.row, { borderTopColor: theme.border }]}
                            accessibilityRole="button"
                        >
                            <Text
                                style={[
                                    styles.label,
                                    {
                                        color: item.destructive
                                            ? theme.danger
                                            : theme.foreground,
                                    },
                                ]}
                            >
                                {item.label}
                            </Text>
                        </Pressable>
                    ))}
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
        gap: 12,
        marginBottom: 6,
    },
    title: {
        flex: 1,
        fontSize: 15,
        fontWeight: "700",
    },
    row: {
        paddingVertical: 15,
        borderTopWidth: StyleSheet.hairlineWidth,
    },
    label: {
        fontSize: 14.5,
        fontWeight: "500",
    },
});
