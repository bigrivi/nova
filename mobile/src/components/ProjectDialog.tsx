import Feather from "@expo/vector-icons/Feather";
import { useEffect, useState } from "react";
import {
    KeyboardAvoidingView,
    Modal,
    Platform,
    Pressable,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "../theme/useTheme";

export function ProjectDialog({
    visible,
    mode,
    initialName = "",
    initialPath = "",
    onSubmit,
    onClose,
}: {
    visible: boolean;
    mode: "create" | "rename";
    initialName?: string;
    initialPath?: string;
    onSubmit: (name: string, path: string | null) => void;
    onClose: () => void;
}) {
    const { theme } = useTheme();
    const insets = useSafeAreaInsets();
    const [name, setName] = useState(initialName);
    const [path, setPath] = useState(initialPath);

    useEffect(() => {
        if (visible) {
            setName(initialName);
            setPath(initialPath);
        }
    }, [visible, initialName, initialPath]);

    const trimmed = name.trim();
    const submit = () => {
        if (!trimmed) {
            return;
        }
        onSubmit(trimmed, path.trim() || null);
    };

    return (
        <Modal
            visible={visible}
            transparent
            animationType="slide"
            onRequestClose={onClose}
        >
            <KeyboardAvoidingView
                style={styles.root}
                behavior={Platform.OS === "ios" ? "padding" : undefined}
            >
                <Pressable
                    style={styles.backdrop}
                    onPress={onClose}
                    accessibilityLabel="Close"
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
                            {mode === "create" ? "New project" : "Rename project"}
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

                    <Text style={[styles.label, { color: theme.weakStrong }]}>
                        Name
                    </Text>
                    <TextInput
                        value={name}
                        onChangeText={setName}
                        placeholder="Project name"
                        placeholderTextColor={theme.weakStrong}
                        autoFocus
                        style={[
                            styles.input,
                            {
                                color: theme.foreground,
                                backgroundColor: theme.muted,
                                borderColor: theme.border,
                            },
                        ]}
                    />

                    <Text
                        style={[
                            styles.label,
                            styles.pathLabel,
                            { color: theme.weakStrong },
                        ]}
                    >
                        Workspace path on the Nova server (optional)
                    </Text>
                    <TextInput
                        value={path}
                        onChangeText={setPath}
                        placeholder="/Users/you/project"
                        placeholderTextColor={theme.weakStrong}
                        autoCapitalize="none"
                        autoCorrect={false}
                        style={[
                            styles.input,
                            {
                                color: theme.foreground,
                                backgroundColor: theme.muted,
                                borderColor: theme.border,
                            },
                        ]}
                    />

                    <View style={styles.actions}>
                        <Pressable
                            onPress={onClose}
                            style={[styles.button, { borderColor: theme.border }]}
                            accessibilityRole="button"
                        >
                            <Text
                                style={[
                                    styles.buttonText,
                                    { color: theme.weakStrong },
                                ]}
                            >
                                Cancel
                            </Text>
                        </Pressable>
                        <Pressable
                            onPress={submit}
                            disabled={!trimmed}
                            style={[
                                styles.button,
                                {
                                    backgroundColor: trimmed
                                        ? theme.primary
                                        : theme.muted,
                                    borderColor: "transparent",
                                },
                            ]}
                            accessibilityRole="button"
                        >
                            <Text
                                style={[
                                    styles.buttonText,
                                    {
                                        color: trimmed
                                            ? theme.primaryForeground
                                            : theme.weak,
                                    },
                                ]}
                            >
                                {mode === "create" ? "Create" : "Save"}
                            </Text>
                        </Pressable>
                    </View>
                </View>
            </KeyboardAvoidingView>
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
        gap: 6,
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 6,
    },
    title: {
        fontSize: 16,
        fontWeight: "700",
    },
    label: {
        fontSize: 12,
        fontWeight: "600",
    },
    pathLabel: {
        marginTop: 8,
    },
    input: {
        height: 44,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 12,
        fontSize: 14,
    },
    actions: {
        flexDirection: "row",
        justifyContent: "flex-end",
        gap: 8,
        marginTop: 12,
    },
    button: {
        minWidth: 86,
        height: 40,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 14,
    },
    buttonText: {
        fontSize: 13,
        fontWeight: "600",
    },
});
