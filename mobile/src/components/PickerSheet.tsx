import Feather from "@expo/vector-icons/Feather";
import {
    Modal,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "../theme/useTheme";

export type PickerItem = {
    id: string;
    label: string;
    description?: string;
};

export type PickerSection = {
    title: string;
    items: PickerItem[];
};

export function PickerSheet({
    visible,
    title,
    items,
    sections,
    selectedId,
    allowDefault = false,
    defaultLabel = "Server default",
    onSelect,
    onClose,
}: {
    visible: boolean;
    title: string;
    items?: PickerItem[];
    sections?: PickerSection[];
    selectedId: string | null;
    allowDefault?: boolean;
    defaultLabel?: string;
    onSelect: (id: string | null) => void;
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
                    accessibilityLabel="Close picker"
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
                        <Text style={[styles.title, { color: theme.foreground }]}>
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

                    <ScrollView style={styles.list}>
                        {allowDefault ? (
                            <Row
                                label={defaultLabel}
                                description="The agent's configured route"
                                selected={selectedId === null}
                                onPress={() => {
                                    onSelect(null);
                                    onClose();
                                }}
                            />
                        ) : null}
                        {items?.map((item) => (
                            <Row
                                key={item.id}
                                label={item.label}
                                description={item.description}
                                selected={selectedId === item.id}
                                onPress={() => {
                                    onSelect(item.id);
                                    onClose();
                                }}
                            />
                        ))}
                        {sections?.map((section) => (
                            <View key={section.title}>
                                <Text
                                    style={[
                                        styles.sectionTitle,
                                        { color: theme.weak },
                                    ]}
                                >
                                    {section.title}
                                </Text>
                                {section.items.map((item) => (
                                    <Row
                                        key={item.id}
                                        label={item.label}
                                        selected={selectedId === item.id}
                                        onPress={() => {
                                            onSelect(item.id);
                                            onClose();
                                        }}
                                    />
                                ))}
                            </View>
                        ))}
                        {(items?.length ?? 0) === 0 &&
                        (sections?.length ?? 0) === 0 ? (
                            <Text
                                style={[
                                    styles.empty,
                                    { color: theme.weakStrong },
                                ]}
                            >
                                Nothing available from this server.
                            </Text>
                        ) : null}
                    </ScrollView>
                </View>
            </View>
        </Modal>
    );
}

function Row({
    label,
    description,
    selected,
    onPress,
}: {
    label: string;
    description?: string;
    selected: boolean;
    onPress: () => void;
}) {
    const { theme } = useTheme();
    return (
        <Pressable
            onPress={onPress}
            style={[styles.row, { borderBottomColor: theme.border }]}
            accessibilityRole="button"
            accessibilityState={{ selected }}
        >
            <View style={styles.rowBody}>
                <Text
                    numberOfLines={1}
                    style={[
                        styles.rowLabel,
                        {
                            color: selected
                                ? theme.brand
                                : theme.foreground,
                        },
                    ]}
                >
                    {label}
                </Text>
                {description ? (
                    <Text
                        numberOfLines={1}
                        style={[styles.rowDescription, { color: theme.weak }]}
                    >
                        {description}
                    </Text>
                ) : null}
            </View>
            {selected ? (
                <Feather name="check" size={16} color={theme.brand} />
            ) : null}
        </Pressable>
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
        maxHeight: "68%",
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
    title: {
        fontSize: 16,
        fontWeight: "700",
    },
    list: {
        flexGrow: 0,
    },
    sectionTitle: {
        marginTop: 14,
        marginBottom: 2,
        fontSize: 10.5,
        fontWeight: "700",
        letterSpacing: 0.8,
        textTransform: "uppercase",
    },
    row: {
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
        paddingVertical: 12,
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    rowBody: {
        flex: 1,
        gap: 2,
    },
    rowLabel: {
        fontSize: 14,
        fontWeight: "500",
    },
    rowDescription: {
        fontSize: 12,
    },
    empty: {
        paddingVertical: 24,
        textAlign: "center",
        fontSize: 13,
    },
});
