import { useRef, type ComponentRef } from "react";
import {
    ActivityIndicator,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { useTheme } from "../theme/useTheme";

export function CompactionBanner({
    visible,
    summary,
}: {
    visible: boolean;
    summary: string;
}) {
    const { theme } = useTheme();
    const scrollRef = useRef<ComponentRef<typeof ScrollView>>(null);

    if (!visible) {
        return null;
    }

    return (
        <View style={styles.wrapper}>
            <View style={styles.line}>
                <ActivityIndicator size="small" color={theme.weak} />
                <Text style={[styles.label, { color: theme.weak }]}>
                    Compacting context…
                </Text>
            </View>
            {summary ? (
                <ScrollView
                    ref={scrollRef}
                    style={[
                        styles.summaryBox,
                        {
                            borderColor: theme.border,
                            backgroundColor: theme.muted,
                        },
                    ]}
                    onContentSizeChange={() =>
                        scrollRef.current?.scrollToEnd({ animated: false })
                    }
                >
                    <Text
                        style={[styles.summary, { color: theme.weakStrong }]}
                    >
                        {summary}
                    </Text>
                </ScrollView>
            ) : null}
        </View>
    );
}

const styles = StyleSheet.create({
    wrapper: {
        paddingHorizontal: 2,
        paddingVertical: 4,
        gap: 4,
    },
    line: {
        flexDirection: "row",
        alignItems: "center",
        gap: 7,
    },
    label: {
        fontSize: 11.5,
    },
    summaryBox: {
        maxHeight: 160,
        borderRadius: 7,
        borderWidth: StyleSheet.hairlineWidth,
        borderStyle: "dashed",
        paddingHorizontal: 8,
        paddingVertical: 6,
    },
    summary: {
        fontFamily: "monospace",
        fontSize: 11,
        lineHeight: 16,
    },
});
