import { useEffect, useState, type ComponentProps } from "react";
import {
    ActivityIndicator,
    KeyboardAvoidingView,
    Platform,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useConnection } from "../state/connection";
import { useTheme } from "../theme/useTheme";

export function ConnectScreen() {
    const { theme } = useTheme();
    const status = useConnection((state) => state.status);
    const error = useConnection((state) => state.error);
    const rememberedUrl = useConnection((state) => state.baseUrl);
    const rememberedUser = useConnection((state) => state.username);
    const connect = useConnection((state) => state.connect);

    const [baseUrl, setBaseUrl] = useState(rememberedUrl);
    const [username, setUsername] = useState(rememberedUser);
    const [password, setPassword] = useState("");
    const busy = status === "connecting";

    useEffect(() => {
        if (!baseUrl && rememberedUrl) {
            setBaseUrl(rememberedUrl);
        }
        if (!username && rememberedUser) {
            setUsername(rememberedUser);
        }
    }, [baseUrl, rememberedUrl, username, rememberedUser]);

    return (
        <SafeAreaView
            style={[styles.safe, { backgroundColor: theme.background }]}
        >
            <KeyboardAvoidingView
                style={styles.flex}
                behavior={Platform.OS === "ios" ? "padding" : undefined}
            >
                <ScrollView
                    contentContainerStyle={styles.content}
                    keyboardShouldPersistTaps="handled"
                >
                    <View style={styles.brandRow}>
                        <View
                            style={[
                                styles.logo,
                                { backgroundColor: theme.brandSoft },
                            ]}
                        >
                            <Text style={[styles.logoText, { color: theme.brand }]}>
                                N
                            </Text>
                        </View>
                        <Text style={[styles.title, { color: theme.foreground }]}>
                            Nova
                        </Text>
                    </View>

                    <Text style={[styles.subtitle, { color: theme.weakStrong }]}>
                        Connect to the Nova server running on your machine.
                    </Text>

                    <View style={styles.form}>
                        <Field
                            label="Server URL"
                            value={baseUrl}
                            onChangeText={setBaseUrl}
                            placeholder="https://nova.example.ts.net"
                            autoCapitalize="none"
                            autoCorrect={false}
                            keyboardType="url"
                            theme={theme}
                        />
                        <Field
                            label="Username"
                            value={username}
                            onChangeText={setUsername}
                            placeholder="Optional"
                            autoCapitalize="none"
                            autoCorrect={false}
                            theme={theme}
                        />
                        <Field
                            label="Password"
                            value={password}
                            onChangeText={setPassword}
                            placeholder="Optional"
                            secureTextEntry
                            theme={theme}
                        />
                    </View>

                    {error ? (
                        <View
                            style={[
                                styles.error,
                                {
                                    backgroundColor: theme.dangerSoft,
                                    borderColor: theme.danger,
                                },
                            ]}
                        >
                            <Text style={{ color: theme.danger }}>{error}</Text>
                        </View>
                    ) : null}

                    <Pressable
                        onPress={() => void connect({ baseUrl, username, password })}
                        disabled={busy || !baseUrl.trim()}
                        style={[
                            styles.button,
                            {
                                backgroundColor:
                                    busy || !baseUrl.trim()
                                        ? theme.muted
                                        : theme.primary,
                            },
                        ]}
                        accessibilityRole="button"
                    >
                        {busy ? (
                            <ActivityIndicator color={theme.primaryForeground} />
                        ) : (
                            <Text
                                style={[
                                    styles.buttonText,
                                    {
                                        color:
                                            busy || !baseUrl.trim()
                                                ? theme.weak
                                                : theme.primaryForeground,
                                    },
                                ]}
                            >
                                Connect
                            </Text>
                        )}
                    </Pressable>

                    <Text style={[styles.hint, { color: theme.weak }]}>
                        Use HTTPS. For a machine at home, Tailscale or a small
                        reverse proxy is the least painful certificate story.
                        The phone never runs the agent or your files.
                    </Text>
                </ScrollView>
            </KeyboardAvoidingView>
        </SafeAreaView>
    );
}

function Field({
    label,
    theme,
    ...props
}: {
    label: string;
    theme: ReturnType<typeof useTheme>["theme"];
} & ComponentProps<typeof TextInput>) {
    return (
        <View style={styles.field}>
            <Text style={[styles.label, { color: theme.weakStrong }]}>
                {label}
            </Text>
            <TextInput
                {...props}
                placeholderTextColor={theme.weakStrong}
                style={[
                    styles.input,
                    {
                        color: theme.foreground,
                        backgroundColor: theme.card,
                        borderColor: theme.border,
                    },
                ]}
            />
        </View>
    );
}

const styles = StyleSheet.create({
    safe: { flex: 1 },
    flex: { flex: 1 },
    content: {
        paddingHorizontal: 24,
        paddingTop: 48,
        paddingBottom: 40,
        gap: 18,
    },
    brandRow: {
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
    },
    logo: {
        width: 40,
        height: 40,
        borderRadius: 12,
        alignItems: "center",
        justifyContent: "center",
    },
    logoText: {
        fontSize: 19,
        fontWeight: "700",
    },
    title: {
        fontSize: 28,
        fontWeight: "700",
    },
    subtitle: {
        fontSize: 14,
        lineHeight: 21,
    },
    form: {
        gap: 12,
    },
    field: {
        gap: 6,
    },
    label: {
        fontSize: 12,
        fontWeight: "600",
    },
    input: {
        height: 46,
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 12,
        fontSize: 15,
    },
    error: {
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 10,
    },
    button: {
        height: 48,
        borderRadius: 12,
        alignItems: "center",
        justifyContent: "center",
    },
    buttonText: {
        fontSize: 15,
        fontWeight: "600",
    },
    hint: {
        fontSize: 12,
        lineHeight: 18,
    },
});
