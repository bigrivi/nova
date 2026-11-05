import Feather from "@expo/vector-icons/Feather";
import {
    RecordingPresets,
    requestRecordingPermissionsAsync,
    setAudioModeAsync,
    useAudioRecorder,
} from "expo-audio";
import { useEffect, useRef, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { getSpeechStatus } from "../api/client";
import { transcribeAudio } from "../lib/speech";
import { useTheme } from "../theme/useTheme";

type Phase = "idle" | "recording" | "transcribing";

function clock(ms: number): string {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function VoiceInputButton({
    onTranscript,
}: {
    onTranscript: (text: string) => void;
}) {
    const { theme } = useTheme();
    const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
    const [enabled, setEnabled] = useState(false);
    const [phase, setPhase] = useState<Phase>("idle");
    const [elapsed, setElapsed] = useState(0);
    const startedAt = useRef(0);

    useEffect(() => {
        let cancelled = false;
        void getSpeechStatus().then((status) => {
            if (!cancelled) {
                setEnabled(status.enabled);
            }
        });
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if (phase !== "recording") {
            return;
        }
        const timer = setInterval(() => {
            setElapsed(Date.now() - startedAt.current);
        }, 500);
        return () => clearInterval(timer);
    }, [phase]);

    useEffect(() => {
        return () => {
            if (recorder.isRecording) {
                void recorder.stop().catch(() => {
                    // The screen is going away; a failed stop is not actionable.
                });
            }
        };
    }, [recorder]);

    if (!enabled) {
        return null;
    }

    const start = async () => {
        try {
            const permission = await requestRecordingPermissionsAsync();
            if (!permission.granted) {
                Alert.alert(
                    "Microphone permission",
                    "Allow microphone access to record a voice note.",
                );
                return;
            }
            await setAudioModeAsync({
                allowsRecording: true,
                playsInSilentMode: true,
            });
            await recorder.prepareToRecordAsync();
            recorder.record();
            startedAt.current = Date.now();
            setElapsed(0);
            setPhase("recording");
        } catch (error) {
            Alert.alert(
                "Could not start recording",
                error instanceof Error ? error.message : String(error),
            );
            setPhase("idle");
        }
    };

    const stop = async () => {
        setPhase("transcribing");
        try {
            await recorder.stop();
            const uri = recorder.uri;
            if (!uri) {
                throw new Error("The recording produced no file");
            }
            const text = await transcribeAudio(uri);
            if (text.trim()) {
                onTranscript(text.trim());
            } else {
                Alert.alert("No speech", "The recording was empty.");
            }
        } catch (error) {
            Alert.alert(
                "Transcription failed",
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            await setAudioModeAsync({ allowsRecording: false }).catch(() => {
                // Releasing the session is best effort.
            });
            setPhase("idle");
            setElapsed(0);
        }
    };

    const cancel = async () => {
        try {
            await recorder.stop();
        } catch {
            // Already stopped or never started; discarding is the point.
        }
        await setAudioModeAsync({ allowsRecording: false }).catch(() => {
            // Releasing the session is best effort.
        });
        setPhase("idle");
        setElapsed(0);
    };

    if (phase === "transcribing") {
        return (
            <View style={styles.pill}>
                <ActivityIndicator size="small" color={theme.weakStrong} />
                <Text style={[styles.statusText, { color: theme.weakStrong }]}>
                    Transcribing
                </Text>
            </View>
        );
    }

    if (phase === "recording") {
        return (
            <View
                style={[
                    styles.pill,
                    { backgroundColor: theme.muted },
                ]}
            >
                <View
                    style={[styles.recordingDot, { backgroundColor: theme.danger }]}
                />
                <Text style={[styles.elapsed, { color: theme.foreground }]}>
                    {clock(elapsed)}
                </Text>
                <Pressable
                    onPress={() => void cancel()}
                    hitSlop={6}
                    accessibilityRole="button"
                    accessibilityLabel="Cancel recording"
                >
                    <Feather name="x" size={14} color={theme.weakStrong} />
                </Pressable>
                <Pressable
                    onPress={() => void stop()}
                    hitSlop={6}
                    accessibilityRole="button"
                    accessibilityLabel="Send voice note"
                >
                    <Feather name="check" size={15} color={theme.success} />
                </Pressable>
            </View>
        );
    }

    return (
        <Pressable
            onPress={() => void start()}
            style={styles.mic}
            accessibilityRole="button"
            accessibilityLabel="Record a voice note"
        >
            <Feather name="mic" size={17} color={theme.weakStrong} />
        </Pressable>
    );
}

const styles = StyleSheet.create({
    mic: {
        width: 30,
        height: 30,
        alignItems: "center",
        justifyContent: "center",
    },
    pill: {
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
        height: 30,
        borderRadius: 15,
        paddingHorizontal: 10,
    },
    recordingDot: {
        width: 7,
        height: 7,
        borderRadius: 4,
    },
    elapsed: {
        fontSize: 12,
        fontWeight: "600",
        fontVariant: ["tabular-nums"],
    },
    statusText: {
        fontSize: 12,
    },
});
