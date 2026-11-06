import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import {
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";

import type { ChatPart, ToolPart } from "../state/chat";
import {
    buildTimelineItems,
    formatDuration,
    toolParamSummary,
    type TimelineItem,
} from "../chat/presentation";
import { buildToolView } from "../chat/tool-view";
import { chatMetrics, toolStatusColors } from "../theme/tokens";
import type { Theme } from "../theme/tokens";
import { useTheme } from "../theme/useTheme";
import {
    mono,
    ToolViewBody,
    ToolViewHeaderMeta,
} from "./ToolViews";

function outcome(
    part: ToolPart,
    theme: Theme,
): {
    background: string;
    foreground: string;
    label: string;
} {
    if (part.status === "running") {
        return {
            background: toolStatusColors.running.background,
            foreground: toolStatusColors.running.foreground,
            label: "running",
        };
    }
    if (part.status === "error") {
        return {
            background: theme.dangerSoft,
            foreground: theme.danger,
            label: "error",
        };
    }
    return {
        background: toolStatusColors.success.background,
        foreground: toolStatusColors.success.foreground,
        label: "done",
    };
}

function ToolRow({
    part,
    inChain = false,
}: {
    part: ToolPart;
    inChain?: boolean;
}) {
    const { theme } = useTheme();
    const [open, setOpen] = useState(false);
    const status = outcome(part, theme);
    const summary = toolParamSummary(part.inputText);
    const view = buildToolView(part);
    const label = view ? view.label : part.toolName;

    return (
        <View>
            <Pressable
                onPress={() => setOpen((value) => !value)}
                style={[
                    styles.toolHeader,
                    inChain ? styles.toolHeaderInChain : null,
                ]}
                accessibilityRole="button"
                accessibilityLabel={`${label} ${status.label}`}
            >
                <View
                    style={[
                        styles.statusDot,
                        { backgroundColor: status.background },
                    ]}
                >
                    <View
                        style={[
                            styles.statusDotInner,
                            { backgroundColor: status.foreground },
                        ]}
                    />
                </View>
                <Text
                    numberOfLines={1}
                    style={[styles.toolName, { color: theme.foreground }]}
                >
                    {label}
                </Text>
                {view ? (
                    <ToolViewHeaderMeta view={view} />
                ) : summary ? (
                    <Text
                        numberOfLines={1}
                        style={[styles.toolSummary, { color: theme.weak }]}
                    >
                        {summary}
                    </Text>
                ) : null}
                <Feather
                    name={open ? "chevron-down" : "chevron-right"}
                    size={14}
                    color={theme.weak}
                    style={styles.toolChevron}
                />
            </Pressable>

            {open ? (
                <View
                    style={[
                        styles.toolBody,
                        {
                            backgroundColor: theme.muted,
                            borderTopColor: theme.border,
                        },
                    ]}
                >
                    {view ? (
                        <ToolViewBody part={part} view={view} />
                    ) : (
                        <>
                            {part.inputText ? (
                                <>
                                    <Text
                                        style={[
                                            styles.bodyLabel,
                                            { color: theme.foreground },
                                        ]}
                                    >
                                        Input
                                    </Text>
                                    <Text
                                        selectable
                                        style={[
                                            styles.code,
                                            { color: theme.weakStrong },
                                        ]}
                                    >
                                        {part.inputText}
                                    </Text>
                                </>
                            ) : null}
                            {part.error ? (
                                <Text
                                    selectable
                                    style={[
                                        styles.error,
                                        { color: theme.danger },
                                    ]}
                                >
                                    {part.error}
                                </Text>
                            ) : null}
                            {part.outputText ? (
                                <>
                                    <Text
                                        style={[
                                            styles.bodyLabel,
                                            styles.resultLabel,
                                            { color: theme.foreground },
                                        ]}
                                    >
                                        Result
                                    </Text>
                                    <Text
                                        selectable
                                        style={[
                                            styles.code,
                                            { color: theme.weakStrong },
                                        ]}
                                    >
                                        {part.outputText}
                                    </Text>
                                </>
                            ) : null}
                        </>
                    )}
                </View>
            ) : null}
        </View>
    );
}

export function ThinkingChain({
    parts,
    item,
    streaming,
}: {
    parts: readonly ChatPart[];
    item: Extract<TimelineItem, { kind: "chain" }>;
    streaming: boolean;
}) {
    const { theme } = useTheme();
    const [userOpen, setUserOpen] = useState<boolean | null>(null);
    const open = userOpen ?? streaming;
    const label = streaming
        ? "Thinking"
        : item.elapsedMs !== null
          ? `Worked for ${formatDuration(item.elapsedMs)}`
          : "Thought";

    return (
        <View
            style={[
                styles.card,
                { backgroundColor: theme.card, borderColor: theme.border },
            ]}
        >
            <Pressable
                onPress={() => setUserOpen(!open)}
                style={styles.cardHeader}
                accessibilityRole="button"
            >
                <Feather name="activity" size={15} color={theme.brand} />
                <Text
                    style={[
                        styles.cardTitle,
                        { color: streaming ? theme.brand : theme.foreground },
                    ]}
                >
                    {label}
                </Text>
                {!streaming && item.toolCount > 0 ? (
                    <Text style={[styles.cardMeta, { color: theme.weak }]}>
                        · {item.toolCount} tool calls
                    </Text>
                ) : null}
                <Feather
                    name={open ? "chevron-down" : "chevron-right"}
                    size={15}
                    color={theme.weak}
                    style={styles.cardChevron}
                />
            </Pressable>

            {open ? (
                <View
                    style={[
                        styles.cardBody,
                        {
                            backgroundColor: theme.muted,
                            borderTopColor: theme.border,
                        },
                    ]}
                >
                    {item.indices.map((index) => {
                        const part = parts[index];
                        if (!part) {
                            return null;
                        }
                        if (part.type === "reasoning") {
                            return (
                                <View key={`r-${index}`} style={styles.reasoningRow}>
                                    <View
                                        style={[
                                            styles.reasoningDot,
                                            {
                                                borderColor: theme.brand,
                                                backgroundColor: theme.card,
                                            },
                                        ]}
                                    />
                                    <View style={styles.reasoningBody}>
                                        <Text
                                            style={[
                                                styles.reasoningLabel,
                                                { color: theme.brand },
                                            ]}
                                        >
                                            Thinking
                                            {part.elapsedMs !== null
                                                ? ` · ${formatDuration(part.elapsedMs)}`
                                                : ""}
                                        </Text>
                                        <Text
                                            selectable
                                            style={[
                                                styles.reasoningText,
                                                { color: theme.weakStrong },
                                            ]}
                                        >
                                            {part.text || "Thinking…"}
                                        </Text>
                                    </View>
                                </View>
                            );
                        }
                        if (part.type === "tool-call") {
                            return (
                                <View
                                    key={part.toolCallId}
                                    style={[
                                        styles.toolInChain,
                                        { borderTopColor: theme.border },
                                    ]}
                                >
                                    <ToolRow part={part} inChain />
                                </View>
                            );
                        }
                        return null;
                    })}
                </View>
            ) : null}
        </View>
    );
}

export function StandaloneToolCard({ part }: { part: ToolPart }) {
    const { theme } = useTheme();
    return (
        <View
            style={[
                styles.card,
                { backgroundColor: theme.card, borderColor: theme.border },
            ]}
        >
            <View
                style={[
                    styles.cardHeader,
                    styles.standaloneHeader,
                    { borderBottomColor: theme.border },
                ]}
            >
                <Feather name="tool" size={14} color={theme.brand} />
                <Text style={[styles.cardTitle, { color: theme.brand }]}>
                    Tool call
                </Text>
                <Text style={[styles.cardMeta, { color: theme.weak }]}>1</Text>
            </View>
            <ToolRow part={part} />
        </View>
    );
}

/** A helper for tests and future custom renderers. */
export function timelineFor(parts: readonly ChatPart[]): TimelineItem[] {
    return buildTimelineItems(parts);
}

const styles = StyleSheet.create({
    card: {
        borderRadius: chatMetrics.cardRadius,
        borderWidth: StyleSheet.hairlineWidth,
        marginBottom: 8,
        overflow: "hidden",
    },
    cardHeader: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: 13,
        paddingVertical: 10,
    },
    standaloneHeader: {
        backgroundColor: "transparent",
        borderBottomWidth: StyleSheet.hairlineWidth,
    },
    cardTitle: {
        fontSize: 13,
        fontWeight: "600",
    },
    cardMeta: {
        fontSize: 12,
    },
    cardChevron: {
        marginLeft: "auto",
    },
    cardBody: {
        borderTopWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 12,
        paddingVertical: 12,
    },
    reasoningRow: {
        flexDirection: "row",
        gap: 8,
        marginBottom: 10,
    },
    reasoningDot: {
        width: 15,
        height: 15,
        borderRadius: 8,
        borderWidth: 2,
        marginTop: 3,
    },
    reasoningBody: {
        flex: 1,
        gap: 2,
    },
    reasoningLabel: {
        fontSize: 12,
        fontWeight: "600",
    },
    reasoningText: {
        fontSize: 13.5,
        lineHeight: 21,
    },
    toolInChain: {
        borderTopWidth: StyleSheet.hairlineWidth,
        paddingTop: 4,
    },
    toolHeaderInChain: {
        paddingHorizontal: 0,
    },
    toolHeader: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingHorizontal: 12,
        paddingVertical: 10,
        minHeight: 40,
    },
    statusDot: {
        width: 15,
        height: 15,
        borderRadius: 8,
        alignItems: "center",
        justifyContent: "center",
    },
    statusDotInner: {
        width: 6,
        height: 6,
        borderRadius: 3,
    },
    toolName: {
        flexShrink: 1,
        fontSize: 12.5,
        fontWeight: "600",
    },
    toolSummary: {
        flex: 1,
        fontSize: 12,
    },
    toolChevron: {
        marginLeft: 2,
    },
    toolBody: {
        borderTopWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 14,
        paddingVertical: 10,
    },
    bodyLabel: {
        fontSize: 11,
        fontWeight: "700",
        marginBottom: 4,
    },
    resultLabel: {
        marginTop: 10,
    },
    code: {
        fontFamily: mono,
        fontSize: 12,
        lineHeight: 19,
    },
    error: {
        fontSize: 12.5,
        lineHeight: 19,
        marginTop: 10,
    },
});
