import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import {
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import type { ApprovalRequest } from "../api/types";
import { useTheme } from "../theme/useTheme";

export function ApprovalSheet({
    approval,
    onResolve,
}: {
    approval: ApprovalRequest;
    onResolve: (approved: boolean, remember: boolean) => void;
}) {
    const { theme } = useTheme();
    const [remember, setRemember] = useState(false);

    return (
        <View
            style={[
                styles.card,
                {
                    backgroundColor: theme.card,
                    borderColor: theme.warning,
                },
            ]}
        >
            <View style={styles.header}>
                <Feather name="shield" size={16} color={theme.warning} />
                <Text style={[styles.title, { color: theme.foreground }]}>
                    Approval needed
                </Text>
                <Text style={[styles.tool, { color: theme.weak }]}>
                    {approval.toolName}
                </Text>
            </View>

            <ScrollView
                style={[
                    styles.commandScroll,
                    { backgroundColor: theme.muted },
                ]}
            >
                <Text
                    selectable
                    style={[styles.command, { color: theme.foreground }]}
                >
                    {approval.command}
                </Text>
            </ScrollView>

            {approval.description ? (
                <Text style={[styles.description, { color: theme.weakStrong }]}>
                    {approval.description}
                </Text>
            ) : null}

            {approval.target ? (
                <Text style={[styles.meta, { color: theme.weak }]}>
                    Target: {approval.target}
                </Text>
            ) : null}

            {approval.rememberable ? (
                <Pressable
                    onPress={() => setRemember((value) => !value)}
                    style={styles.rememberRow}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: remember }}
                >
                    <View
                        style={[
                            styles.checkbox,
                            {
                                borderColor: theme.border,
                                backgroundColor: remember
                                    ? theme.brand
                                    : "transparent",
                            },
                        ]}
                    >
                        {remember ? (
                            <Feather
                                name="check"
                                size={11}
                                color={theme.onBrand}
                            />
                        ) : null}
                    </View>
                    <Text style={[styles.rememberText, { color: theme.weakStrong }]}>
                        Remember this approval
                    </Text>
                </Pressable>
            ) : null}

            <View style={styles.actions}>
                <Pressable
                    onPress={() => onResolve(false, false)}
                    style={[
                        styles.button,
                        { borderColor: theme.border },
                    ]}
                    accessibilityRole="button"
                >
                    <Text style={[styles.buttonText, { color: theme.danger }]}>
                        Reject
                    </Text>
                </Pressable>
                <Pressable
                    onPress={() => onResolve(true, remember)}
                    style={[
                        styles.button,
                        styles.approve,
                        { backgroundColor: theme.primary },
                    ]}
                    accessibilityRole="button"
                >
                    <Text
                        style={[
                            styles.buttonText,
                            { color: theme.primaryForeground },
                        ]}
                    >
                        Approve
                    </Text>
                </Pressable>
            </View>
        </View>
    );
}

export function InputNotice({ message }: { message: string }) {
    const { theme } = useTheme();
    return (
        <View
            style={[
                styles.notice,
                {
                    backgroundColor: theme.brandSoft,
                    borderColor: theme.brand,
                },
            ]}
        >
            <Feather name="message-circle" size={15} color={theme.brand} />
            <View style={styles.noticeBody}>
                <Text style={[styles.noticeText, { color: theme.brand }]}>
                    {message}
                </Text>
                <Text style={[styles.noticeHint, { color: theme.weakStrong }]}>
                    The question form could not be recovered. Continue in
                    the web UI or TUI.
                </Text>
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    card: {
        borderRadius: 12,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 12,
        gap: 8,
    },
    header: {
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
    },
    title: {
        fontSize: 13.5,
        fontWeight: "700",
    },
    tool: {
        marginLeft: "auto",
        fontSize: 11.5,
    },
    commandScroll: {
        maxHeight: 130,
        borderRadius: 8,
        padding: 8,
    },
    command: {
        fontFamily: "monospace",
        fontSize: 12,
        lineHeight: 18,
    },
    description: {
        fontSize: 12.5,
        lineHeight: 18,
    },
    meta: {
        fontSize: 11,
    },
    rememberRow: {
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
        paddingVertical: 2,
    },
    checkbox: {
        width: 16,
        height: 16,
        borderRadius: 4,
        borderWidth: 1,
        alignItems: "center",
        justifyContent: "center",
    },
    rememberText: {
        fontSize: 12,
    },
    actions: {
        flexDirection: "row",
        justifyContent: "flex-end",
        gap: 8,
        marginTop: 2,
    },
    button: {
        minWidth: 86,
        height: 36,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: 14,
    },
    approve: {
        borderWidth: 0,
    },
    buttonText: {
        fontSize: 13,
        fontWeight: "600",
    },
    notice: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 10,
    },
    noticeText: {
        flex: 1,
        fontSize: 12.5,
        lineHeight: 18,
    },
    noticeBody: {
        flex: 1,
        gap: 3,
    },
    noticeHint: {
        fontSize: 11,
        lineHeight: 16,
    },
});
