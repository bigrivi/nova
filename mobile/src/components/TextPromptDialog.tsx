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

export function TextPromptDialog({
    visible,
    title,
    initialValue = "",
    placeholder,
    submitLabel = "Save",
    onSubmit,
    onClose,
}: {
    visible: boolean;
    title: string;
    initialValue?: string;
    placeholder?: string;
    submitLabel?: string;
    onSubmit: (value: string) => void;
    onClose: () => void;
}) {
    const { theme } = useTheme();
    const insets = useSafeAreaInsets();
    const [value, setValue] = useState(initialValue);

    useEffect(() => {
        if (visible) {
            setValue(initialValue);
        }
    }, [visible, initialValue]);

    const trimmed = value.trim();
    const submit = () => {
        if (trimmed) {
            onSubmit(trimmed);
        }
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
                        <Text
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
                    <TextInput
                        value={value}
                        onChangeText={setValue}
                        placeholder={placeholder}
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
                        onSubmitEditing={submit}
                        returnKeyType="done"
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
                                {submitLabel}
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
        gap: 10,
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
    },
    title: {
        fontSize: 16,
        fontWeight: "700",
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
        marginTop: 2,
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
