import { useEffect, useRef, useState } from "react";
import {
    AccessibilityInfo,
    Animated,
    StyleSheet,
    Text,
    View,
} from "react-native";

import type { RetryState } from "../state/chat";
import { useTheme } from "../theme/useTheme";

/** The three-dot wait state, matching the web's `ThinkingIndicator`. */
export function ThinkingIndicator({ retry }: { retry: RetryState | null }) {
    const { theme } = useTheme();
    const values = useRef([
        new Animated.Value(0),
        new Animated.Value(0),
        new Animated.Value(0),
    ]).current;
    const [reduceMotion, setReduceMotion] = useState(false);

    useEffect(() => {
        let active = true;
        void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
            if (active) {
                setReduceMotion(enabled);
            }
        });
        const subscription = AccessibilityInfo.addEventListener(
            "reduceMotionChanged",
            setReduceMotion,
        );
        return () => {
            active = false;
            subscription.remove();
        };
    }, []);

    useEffect(() => {
        if (reduceMotion) {
            for (const value of values) {
                value.setValue(0);
            }
            return;
        }
        const animations = values.map((value, index) =>
            Animated.loop(
                Animated.sequence([
                    Animated.delay(index * 140),
                    Animated.timing(value, {
                        toValue: -3,
                        duration: 160,
                        useNativeDriver: true,
                    }),
                    Animated.timing(value, {
                        toValue: 0,
                        duration: 160,
                        useNativeDriver: true,
                    }),
                    Animated.delay(280),
                ]),
            ),
        );
        animations.forEach((animation) => animation.start());
        return () => animations.forEach((animation) => animation.stop());
    }, [reduceMotion, values]);

    const color = retry ? theme.warning : theme.mutedForeground;

    return (
        <View
            style={styles.row}
            accessibilityRole="progressbar"
            accessibilityLabel={retry ? "Retrying" : "Thinking"}
        >
            <View
                style={styles.dots}
                accessible={false}
                importantForAccessibility="no-hide-descendants"
            >
                {values.map((value, index) => (
                    <Animated.View
                        key={index}
                        style={[
                            styles.dot,
                            {
                                backgroundColor: color,
                                transform: [{ translateY: value }],
                            },
                        ]}
                    />
                ))}
            </View>
            {retry ? (
                <Text
                    numberOfLines={3}
                    style={[styles.retry, { color: theme.warning }]}
                >
                    Retrying · attempt {retry.attempt}/{retry.total}
                    {retry.reason ? ` · ${retry.reason}` : ""}
                </Text>
            ) : null}
        </View>
    );
}

const styles = StyleSheet.create({
    row: {
        flexDirection: "row",
        alignItems: "flex-start",
        gap: 8,
        paddingVertical: 4,
    },
    dots: {
        flexDirection: "row",
        gap: 3,
        paddingTop: 7,
    },
    dot: {
        width: 6,
        height: 6,
        borderRadius: 3,
    },
    retry: {
        flex: 1,
        fontSize: 13,
        lineHeight: 19,
    },
});
