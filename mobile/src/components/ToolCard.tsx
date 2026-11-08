import Feather from "@expo/vector-icons/Feather";
import { useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";

import type { ApprovalRequest } from "../api/types";
import type { ChatPart, ToolPart } from "../state/chat";
import {
    buildTimelineItems,
    formatDuration,
    toolParamSummary,
    type TimelineItem,
} from "../chat/presentation";
import { buildToolView, readBackgroundTaskId } from "../chat/tool-view";
import {
    readToolState,
    toolStateLabel,
    type ToolState,
} from "../chat/tool-state";
import { useTasks } from "../state/tasks";
import { chatMetrics, toolStatusColors } from "../theme/tokens";
import type { Theme } from "../theme/tokens";
import { useTheme } from "../theme/useTheme";
import {
    mono,
    ToolViewBody,
    ToolViewHeaderMeta,
} from "./ToolViews";

function stateColors(
    state: ToolState,
    theme: Theme,
): { background: string; foreground: string; label: string } {
    if (state === "waiting" || state === "running") {
        return {
            background: toolStatusColors.running.background,
            foreground: toolStatusColors.running.foreground,
            label: toolStateLabel(state),
        };
    }
    if (state === "error") {
        return {
            background: theme.dangerSoft,
            foreground: theme.danger,
            label: "error",
        };
    }
    if (state === "cancelled") {
        return {
            background: theme.muted,
            foreground: theme.weak,
            label: "cancelled",
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
    waiting = false,
}: {
    part: ToolPart;
    inChain?: boolean;
    waiting?: boolean;
}) {
    const { theme } = useTheme();
    const [open, setOpen] = useState(false);
    const taskId = readBackgroundTaskId(part.outputText);
    const task = useTasks((state) =>
        taskId ? state.byId[taskId] : undefined,
    );
    const state = readToolState({
        status: part.status,
        taskStatus: task?.status,
        waiting,
    });
    const status = stateColors(state, theme);
    const summary = toolParamSummary(part.inputText);
    const view = buildToolView(part);
    const label = view ? view.label : part.toolName;
    const taskFailure =
        state === "error" && task?.status ? task.status : null;

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
                    {state === "running" ? (
                        <ActivityIndicator
                            size="small"
                            color={status.foreground}
                            style={styles.spinner}
                        />
                    ) : (
                        <View
                            style={[
                                styles.statusDotInner,
                                { backgroundColor: status.foreground },
                            ]}
                        />
                    )}
                </View>
                <Text
                    numberOfLines={1}
                    style={[styles.toolName, { color: theme.foreground }]}
                >
                    {label}
                </Text>
                {state === "waiting" ? (
                    <Text
                        numberOfLines={1}
                        style={[
                            styles.toolState,
                            { color: status.foreground },
                        ]}
                    >
                        waiting for approval
                    </Text>
                ) : taskFailure ? (
                    <Text
                        numberOfLines={1}
                        style={[
                            styles.toolState,
                            { color: status.foreground },
                        ]}
                    >
                        {taskFailure}
                    </Text>
                ) : state === "cancelled" ? (
                    <Text
                        numberOfLines={1}
                        style={[styles.toolState, { color: theme.weak }]}
                    >
                        cancelled
                    </Text>
                ) : view ? (
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
    approval = null,
}: {
    parts: readonly ChatPart[];
    item: Extract<TimelineItem, { kind: "chain" }>;
    streaming: boolean;
    approval?: ApprovalRequest | null;
}) {
    const { theme } = useTheme();
    const [userOpen, setUserOpen] = useState<boolean | null>(null);
    const open = userOpen ?? streaming;
    const waitingIndex = (() => {
        if (!approval) {
            return -1;
        }
        for (let position = item.indices.length - 1; position >= 0; position -= 1) {
            const index = item.indices[position]!;
            const candidate = parts[index];
            if (
                candidate?.type === "tool-call" &&
                candidate.status === "running" &&
                candidate.toolName === approval.toolName
            ) {
                return index;
            }
        }
        return -1;
    })();
    const waiting = waitingIndex !== -1;
    const label = waiting
        ? "Waiting for approval"
        : streaming
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
                <Feather
                    name={waiting ? "clock" : "activity"}
                    size={15}
                    color={
                        waiting
                            ? toolStatusColors.running.foreground
                            : theme.brand
                    }
                />
                <Text
                    style={[
                        styles.cardTitle,
                        {
                            color: waiting
                                ? toolStatusColors.running.foreground
                                : streaming
                                  ? theme.brand
                                  : theme.foreground,
                        },
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
                                    <ToolRow
                                        part={part}
                                        inChain
                                        waiting={index === waitingIndex}
                                    />
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

export function StandaloneToolCard({
    part,
    approval = null,
}: {
    part: ToolPart;
    approval?: ApprovalRequest | null;
}) {
    const { theme } = useTheme();
    const waiting = Boolean(
        approval &&
            part.status === "running" &&
            part.toolName === approval.toolName,
    );
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
            <ToolRow part={part} waiting={waiting} />
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
        marginTop: 0,
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
    toolState: {
        flexShrink: 1,
        fontSize: 11.5,
        fontWeight: "600",
    },
    spinner: {
        transform: [{ scale: 0.7 }],
    },
    toolChevron: {
        marginLeft: 2,
    },
    toolBody: {
        borderTopWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 12,
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
