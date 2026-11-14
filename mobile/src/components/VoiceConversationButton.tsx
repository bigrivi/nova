import Feather from "@expo/vector-icons/Feather";
import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync } from "expo-audio";
import AudioModule from "expo-audio/build/AudioModule";
import { createRecordingOptions } from "expo-audio/build/utils/options";
import { useCallback, useEffect, useRef, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Animated,
    Modal,
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { runTurn } from "../lib/stream-runner";
import { transcribeAudio } from "../lib/speech";
import { speakText } from "../lib/tts";
import { useChat } from "../state/chat";
import { useTheme } from "../theme/useTheme";

type Phase = "idle" | "recording" | "transcribing" | "thinking" | "speaking";

const PHASE_LABEL: Record<Phase, string> = {
    idle: "Tap to speak",
    recording: "Listening…",
    transcribing: "Transcribing…",
    thinking: "Thinking…",
    speaking: "Speaking…",
};

/** Trigger button in the composer; the session itself lives in the modal. */
export function VoiceConversationButton({
    tabId,
    streaming,
    active,
    onToggle,
}: {
    tabId: string;
    streaming: boolean;
    active: boolean;
    onToggle: (active: boolean) => void;
}) {
    return (
        <>
            <Pressable
                onPress={() => onToggle(true)}
                style={styles.fab}
                accessibilityRole="button"
                accessibilityLabel="Start voice conversation"
            >
                <Feather name="mic" size={14} color="#fff" />
            </Pressable>
            <Modal
                visible={active}
                animationType="fade"
                onRequestClose={() => onToggle(false)}
            >
                {active ? (
                    <VoiceSession
                        tabId={tabId}
                        streaming={streaming}
                        onClose={() => onToggle(false)}
                    />
                ) : null}
            </Modal>
        </>
    );
}

function VoiceSession({
    tabId,
    onClose,
}: {
    tabId: string;
    streaming: boolean;
    onClose: () => void;
}) {
    const { theme } = useTheme();
    const recorderRef = useRef<any>(null);
    const [phase, setPhase] = useState<Phase>("idle");
    const [continuous, setContinuous] = useState(true);
    const pulse = useRef(new Animated.Value(1)).current;
    const closed = useRef(false);

    useEffect(() => {
        if (phase !== "recording") {
            pulse.setValue(1);
            return;
        }
        const loop = Animated.loop(
            Animated.sequence([
                Animated.timing(pulse, {
                    toValue: 1.15,
                    duration: 700,
                    useNativeDriver: true,
                }),
                Animated.timing(pulse, {
                    toValue: 1,
                    duration: 700,
                    useNativeDriver: true,
                }),
            ]),
        );
        loop.start();
        return () => loop.stop();
    }, [phase, pulse]);

    const startRecording = useCallback(async () => {
        if (closed.current) return false;
        const perm = await requestRecordingPermissionsAsync();
        if (!perm.granted) {
            Alert.alert("Microphone", "Permission required.");
            return false;
        }
        try {
            await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
            const options = createRecordingOptions(RecordingPresets.HIGH_QUALITY);
            const recorder = new AudioModule.AudioRecorder(options as any);
            recorderRef.current = recorder;
            await recorder.prepareToRecordAsync();
            recorder.record();
            setPhase("recording");
            return true;
        } catch (e) {
            Alert.alert("Microphone", e instanceof Error ? e.message : String(e));
            setPhase("idle");
            return false;
        }
    }, []);

    useEffect(() => {
        return () => {
            closed.current = true;
            const rec = recorderRef.current;
            recorderRef.current = null;
            if (rec) {
                void rec
                    .stop()
                    .catch(() => {})
                    .then(() => rec.release?.());
            }
            void setAudioModeAsync({ allowsRecording: false }).catch(() => {});
        };
    }, []);

    const waitStreamingDone = useCallback(async () => {
        let waited = 0;
        while (!useChat.getState().byId[tabId]?.streaming && waited < 10000) {
            await new Promise((r) => setTimeout(r, 200));
            waited += 200;
        }
        while (useChat.getState().byId[tabId]?.streaming) {
            await new Promise((r) => setTimeout(r, 300));
        }
    }, [tabId]);

    const getLastAssistantText = useCallback(() => {
        const msgs = useChat.getState().byId[tabId]?.messages ?? [];
        for (let i = msgs.length - 1; i >= 0; i--) {
            const m = msgs[i] as any;
            if (m.role === "assistant") {
                const parts = Array.isArray(m.parts) ? m.parts : [];
                return parts
                    .filter((p: any) => p?.type === "text")
                    .map((p: any) => p.text)
                    .join("\n")
                    .trim();
            }
        }
        return "";
    }, [tabId]);

    const stopAndSend = useCallback(async () => {
        setPhase("transcribing");
        try {
            const recorder = recorderRef.current;
            if (!recorder) throw new Error("recorder not ready");
            await recorder.stop();
            const uri = recorder.uri;
            recorder.release?.();
            recorderRef.current = null;
            if (!uri) throw new Error("no recording");
            const t0 = Date.now();
            const text = await transcribeAudio(uri);
            console.log("VC transcribe ms:", Date.now() - t0);
            if (!text.trim()) {
                setPhase("idle");
                return;
            }
            setPhase("thinking");
            const t1 = Date.now();
            runTurn(tabId, text.trim(), []);
            await waitStreamingDone();
            console.log("VC stream ms:", Date.now() - t1);
            const reply = getLastAssistantText();
            if (reply) {
                setPhase("speaking");
                const t2 = Date.now();
                await speakText(reply);
                console.log("VC tts+play ms:", Date.now() - t2);
            }
            setPhase("idle");
            if (!closed.current && continuous) {
                await startRecording();
            }
        } catch (e) {
            if (!closed.current) {
                Alert.alert("Error", e instanceof Error ? e.message : String(e));
                setPhase("idle");
            }
        } finally {
            if (!closed.current) {
                await setAudioModeAsync({ allowsRecording: false }).catch(() => {});
            }
        }
    }, [
        tabId,
        continuous,
        waitStreamingDone,
        getLastAssistantText,
        startRecording,
    ]);

    const busy = phase === "transcribing" || phase === "thinking";
    const orbColor = phase === "recording" ? theme.danger : theme.brand;

    return (
        <View style={[styles.screen, { backgroundColor: theme.background }]}>
            <View style={styles.header}>
                <Pressable onPress={onClose} hitSlop={10} style={styles.headerBtn}>
                    <Feather name="chevron-down" size={24} color={theme.foreground} />
                </Pressable>
                <Text style={[styles.title, { color: theme.foreground }]}>
                    Voice Practice
                </Text>
                <Pressable
                    onPress={() => setContinuous((c) => !c)}
                    style={[styles.mode, { borderColor: theme.border }]}
                >
                    <Feather
                        name="repeat"
                        size={12}
                        color={theme.weakStrong}
                    />
                    <Text style={[styles.modeText, { color: theme.weakStrong }]}>
                        {continuous ? "Auto" : "Manual"}
                    </Text>
                </Pressable>
            </View>

            <View style={styles.center}>
                <Animated.View
                    style={[
                        styles.orb,
                        {
                            backgroundColor: `${orbColor}18`,
                            borderColor: orbColor,
                            transform: [{ scale: pulse }],
                        },
                    ]}
                >
                    {busy ? (
                        <ActivityIndicator size="large" color={orbColor} />
                    ) : phase === "speaking" ? (
                        <Feather name="volume-2" size={48} color={orbColor} />
                    ) : (
                        <Feather name="mic" size={48} color={orbColor} />
                    )}
                </Animated.View>
                <Text style={[styles.status, { color: theme.foreground }]}>
                    {PHASE_LABEL[phase]}
                </Text>
                <Text style={[styles.sub, { color: theme.weakStrong }]}>
                    {phase === "recording"
                        ? "Speak naturally, then tap the check."
                        : phase === "speaking"
                          ? "Alex is reading the reply aloud."
                          : phase === "idle"
                            ? "Tap the button below to start another turn."
                            : "Please wait…"}
                </Text>
            </View>

            <View style={styles.bottom}>
                {phase === "recording" ? (
                    <Pressable
                        onPress={() => void stopAndSend()}
                        style={[styles.primary, { backgroundColor: theme.foreground }]}
                    >
                        <Feather name="check" size={26} color={theme.background} />
                    </Pressable>
                ) : (
                    <Pressable
                        onPress={() => void startRecording()}
                        disabled={busy}
                        style={[
                            styles.primary,
                            { backgroundColor: busy ? theme.muted : theme.foreground },
                        ]}
                    >
                        <Feather
                            name="mic"
                            size={26}
                            color={busy ? theme.weakStrong : theme.background}
                        />
                    </Pressable>
                )}
            </View>
        </View>
    );
}

const styles = StyleSheet.create({
    fab: {
        width: 28,
        height: 28,
        borderRadius: 14,
        marginRight: 6,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#1f1f1f",
    },
    screen: { flex: 1, paddingHorizontal: 24, paddingVertical: 16 },
    header: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        marginTop: 8,
    },
    headerBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center" },
    title: { fontSize: 16, fontWeight: "600" },
    mode: {
        flexDirection: "row",
        alignItems: "center",
        gap: 5,
        borderWidth: 1,
        borderRadius: 14,
        paddingHorizontal: 10,
        paddingVertical: 5,
    },
    modeText: { fontSize: 11, fontWeight: "600" },
    center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 22 },
    orb: {
        width: 160,
        height: 160,
        borderRadius: 80,
        alignItems: "center",
        justifyContent: "center",
        borderWidth: 2,
    },
    status: { fontSize: 22, fontWeight: "600" },
    sub: { fontSize: 13, textAlign: "center", maxWidth: 280 },
    bottom: { alignItems: "center", paddingBottom: 28 },
    primary: {
        width: 72,
        height: 72,
        borderRadius: 36,
        alignItems: "center",
        justifyContent: "center",
    },
});
