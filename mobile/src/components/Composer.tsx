import Feather from "@expo/vector-icons/Feather";
import { useMemo, useState } from "react";
import {
    Image,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";

import type { ContextUsage, NovaAgent } from "../api/types";
import {
    applyMention,
    detectMention,
    filterSubagentsByQuery,
} from "../chat/mention";
import { contextRingWarns } from "../chat/presentation";
import {
    useAttachments,
    type PendingAttachment,
} from "../state/attachments";
import { useDrafts } from "../state/drafts";
import { chatMetrics } from "../theme/tokens";
import { useTheme } from "../theme/useTheme";
import { ImagePreview } from "./ImagePreview";

const NO_ATTACHMENTS: PendingAttachment[] = [];

/** Route chips and the pickers they open. */
export type ComposerRoute = {
    agentLabel: string;
    modelLabel: string;
    effortLabel: string | null;
    projectLabel: string | null;
    canPickAgent: boolean;
    canPickEffort: boolean;
    canPickProject: boolean;
    canClearProject: boolean;
    subagents: NovaAgent[];
    onPickAgent: () => void;
    onPickModel: () => void;
    onPickEffort: () => void;
    onPickProject: () => void;
    onClearProject: () => void;
};

/** What the composer can do to the turn. */
export type ComposerActions = {
    onAddAttachment: () => void;
    onSend: (text: string, attachments: PendingAttachment[]) => void;
    onStop: () => void;
    onVoiceConversation?: () => void;
};

export function Composer({
    tabId,
    streaming,
    context,
    route,
    actions,
    showDisclaimer = false,
}: {
    tabId: string;
    streaming: boolean;
    context: ContextUsage | null;
    route: ComposerRoute;
    actions: ComposerActions;
    showDisclaimer?: boolean;
}) {
    const {
        agentLabel,
        modelLabel,
        effortLabel,
        projectLabel,
        canPickAgent,
        canPickEffort,
        canPickProject,
        canClearProject,
        subagents,
        onPickAgent,
        onPickModel,
        onPickEffort,
        onPickProject,
        onClearProject,
    } = route;
    const { onAddAttachment, onSend, onStop, onVoiceConversation } = actions;

    const { theme } = useTheme();
    const text = useDrafts((state) => state.byTab[tabId] ?? "");
    const setText = useDrafts((state) => state.setText);
    const clear = useDrafts((state) => state.clear);
    const attachments = useAttachments(
        // A literal [] here would be a new snapshot on every render and send
        // useSyncExternalStore into an infinite loop.
        (state) => state.byTab[tabId] ?? NO_ATTACHMENTS,
    );
    const removeAttachment = useAttachments((state) => state.remove);
    const canSend =
        (text.trim().length > 0 || attachments.length > 0) && !streaming;
    const warn = context ? contextRingWarns(context.percent) : false;
    const [inputHeight, setInputHeight] = useState(40);
    const [previewUri, setPreviewUri] = useState<string | null>(null);
    const mention = text.length > 0 ? detectMention(text, text.length) : null;
    const matches = mention
        ? filterSubagentsByQuery(subagents, mention.query)
        : [];

    const contextLabel = useMemo(() => {
        if (!context || context.limit <= 0) {
            return null;
        }
        return `${Math.round(context.percent)}%`;
    }, [context]);

    const send = () => {
        if (!canSend) {
            return;
        }
        const value = text;
        clear(tabId);
        setInputHeight(40);
        onSend(value, attachments);
    };

    return (
        <View style={styles.wrapper}>
            <View
                style={[
                    styles.shell,
                    {
                        backgroundColor: theme.card,
                        borderColor: theme.border,
                    },
                ]}
            >
                <View style={styles.contextBar}>
                    <View style={styles.contextLeft}>
                        <Pressable
                            onPress={onPickAgent}
                            disabled={!canPickAgent}
                            style={[
                                styles.agentChip,
                                { backgroundColor: theme.muted },
                                !canPickAgent && styles.readOnlyChip,
                            ]}
                            accessibilityRole="button"
                            accessibilityLabel="Choose agent"
                        >
                            <View
                                style={[
                                    styles.agentDot,
                                    { backgroundColor: theme.brand },
                                ]}
                            />
                            <Text
                                numberOfLines={1}
                                style={[
                                    styles.agentText,
                                    { color: theme.weakStrong },
                                ]}
                            >
                                {agentLabel}
                            </Text>
                        </Pressable>
                        <Pressable
                            onPress={onPickModel}
                            style={[
                                styles.modelChip,
                                { borderColor: theme.border },
                            ]}
                            accessibilityRole="button"
                            accessibilityLabel="Choose model"
                        >
                            <Feather
                                name="cpu"
                                size={11}
                                color={theme.weakStrong}
                            />
                            <Text
                                numberOfLines={1}
                                style={[
                                    styles.modelText,
                                    { color: theme.weakStrong },
                                ]}
                            >
                                {modelLabel}
                            </Text>
                        </Pressable>
                        {canPickEffort ? (
                            <Pressable
                                onPress={onPickEffort}
                                style={[
                                    styles.modelChip,
                                    { borderColor: theme.border },
                                ]}
                                accessibilityRole="button"
                                accessibilityLabel="Choose reasoning effort"
                            >
                                <Feather
                                    name="sliders"
                                    size={11}
                                    color={theme.weakStrong}
                                />
                                <Text
                                    numberOfLines={1}
                                    style={[
                                        styles.modelText,
                                        { color: theme.weakStrong },
                                    ]}
                                >
                                    {effortLabel ?? "Default"}
                                </Text>
                            </Pressable>
                        ) : null}
                        <Pressable
                            onPress={onPickProject}
                            disabled={!canPickProject}
                            style={[
                                styles.modelChip,
                                { borderColor: theme.border },
                                !canPickProject && styles.readOnlyChip,
                            ]}
                            accessibilityRole="button"
                            accessibilityLabel="Choose project"
                        >
                            <Feather
                                name="folder"
                                size={11}
                                color={theme.weakStrong}
                            />
                            <Text
                                numberOfLines={1}
                                style={[
                                    styles.modelText,
                                    { color: theme.weakStrong },
                                ]}
                            >
                                {projectLabel ?? "Project"}
                            </Text>
                            {canClearProject ? (
                                <Pressable
                                    onPress={(event) => {
                                        event.stopPropagation();
                                        onClearProject();
                                    }}
                                    hitSlop={6}
                                    accessibilityRole="button"
                                    accessibilityLabel="Clear project"
                                >
                                    <Feather
                                        name="x"
                                        size={10}
                                        color={theme.weak}
                                    />
                                </Pressable>
                            ) : null}
                        </Pressable>
                    </View>
                    {contextLabel ? (
                        <Text
                            style={[
                                styles.contextText,
                                { color: warn ? theme.danger : theme.weak },
                            ]}
                        >
                            {contextLabel}
                        </Text>
                    ) : null}
                </View>

                {attachments.length > 0 ? (
                    <ScrollView
                        horizontal
                        showsHorizontalScrollIndicator={false}
                        contentContainerStyle={styles.attachmentRow}
                    >
                        {attachments.map((attachment) =>
                            attachment.kind === "image" ? (
                                <View
                                    key={attachment.id}
                                    style={styles.attachmentTile}
                                >
                                    <Pressable
                                        onPress={() =>
                                            setPreviewUri(attachment.previewUri)
                                        }
                                        accessibilityRole="imagebutton"
                                        accessibilityLabel={`Preview ${attachment.name}`}
                                    >
                                        <Image
                                            source={{ uri: attachment.previewUri }}
                                            style={styles.attachmentImage}
                                        />
                                    </Pressable>
                                    <Pressable
                                        onPress={() =>
                                            removeAttachment(
                                                tabId,
                                                attachment.id,
                                            )
                                        }
                                        style={[
                                            styles.attachmentRemove,
                                            {
                                                backgroundColor: theme.card,
                                                borderColor: theme.border,
                                            },
                                        ]}
                                        hitSlop={6}
                                        accessibilityRole="button"
                                        accessibilityLabel={`Remove ${attachment.name}`}
                                    >
                                        <Feather
                                            name="x"
                                            size={10}
                                            color={theme.weakStrong}
                                        />
                                    </Pressable>
                                </View>
                            ) : (
                                <View
                                    key={attachment.id}
                                    style={[
                                        styles.documentChip,
                                        {
                                            backgroundColor: theme.muted,
                                            borderColor: theme.border,
                                        },
                                    ]}
                                >
                                    <Feather
                                        name="file-text"
                                        size={14}
                                        color={theme.weakStrong}
                                    />
                                    <Text
                                        numberOfLines={1}
                                        style={[
                                            styles.documentName,
                                            { color: theme.weakStrong },
                                        ]}
                                    >
                                        {attachment.name}
                                    </Text>
                                    <Pressable
                                        onPress={() =>
                                            removeAttachment(
                                                tabId,
                                                attachment.id,
                                            )
                                        }
                                        hitSlop={6}
                                        accessibilityRole="button"
                                        accessibilityLabel={`Remove ${attachment.name}`}
                                    >
                                        <Feather
                                            name="x"
                                            size={11}
                                            color={theme.weak}
                                        />
                                    </Pressable>
                                </View>
                            ),
                        )}
                    </ScrollView>
                ) : null}

                {mention && matches.length > 0 && !streaming ? (
                    <ScrollView
                        horizontal
                        showsHorizontalScrollIndicator={false}
                        contentContainerStyle={styles.mentionRow}
                    >
                        {matches.map((agent) => (
                            <Pressable
                                key={agent.key}
                                onPress={() => {
                                    const next = applyMention(
                                        text,
                                        mention,
                                        agent.key,
                                    );
                                    setText(tabId, next.text);
                                }}
                                style={[
                                    styles.mentionChip,
                                    {
                                        backgroundColor: theme.brandSoft,
                                        borderColor: theme.brand,
                                    },
                                ]}
                                accessibilityRole="button"
                            >
                                <Text
                                    numberOfLines={1}
                                    style={[
                                        styles.mentionText,
                                        { color: theme.brand },
                                    ]}
                                >
                                    @{agent.name || agent.key}
                                </Text>
                            </Pressable>
                        ))}
                    </ScrollView>
                ) : null}

                <TextInput
                    value={text}
                    onChangeText={(value) => setText(tabId, value)}
                    placeholder="Send a message"
                    placeholderTextColor={theme.weakStrong}
                    multiline
                    editable={!streaming}
                    onContentSizeChange={(event) => {
                        const next = Math.min(
                            chatMetrics.composerTextMaxHeight,
                            Math.max(
                                chatMetrics.composerTextMinHeight,
                                event.nativeEvent.contentSize.height,
                            ),
                        );
                        setInputHeight(next);
                    }}
                    style={[
                        styles.input,
                        { color: theme.foreground, height: inputHeight },
                    ]}
                    textAlignVertical="top"
                    accessibilityLabel="Message input"
                />

                <View style={styles.footer}>
                    <View style={styles.footerLeft}>
                        <Pressable
                            onPress={onAddAttachment}
                            disabled={streaming}
                            style={styles.addButton}
                            accessibilityRole="button"
                            accessibilityLabel="Add image"
                        >
                            <Feather
                                name="image"
                                size={17}
                                color={theme.weakStrong}
                            />
                        </Pressable>
                        <Text style={[styles.hint, { color: theme.weak }]}>
                            {streaming ? "Working" : "Enter for a new line"}
                        </Text>
                    </View>
                    {onVoiceConversation ? (
                        <Pressable
                            onPress={onVoiceConversation}
                            style={styles.voiceButton}
                            accessibilityRole="button"
                            accessibilityLabel="Start voice conversation"
                        >
                            <Feather name="mic" size={14} color="#fff" />
                        </Pressable>
                    ) : null}
                    {streaming ? (
                        <Pressable
                            onPress={onStop}
                            style={[
                                styles.action,
                                { backgroundColor: theme.primary },
                            ]}
                            accessibilityRole="button"
                            accessibilityLabel="Stop"
                        >
                            <Feather
                                name="square"
                                size={14}
                                color={theme.primaryForeground}
                            />
                        </Pressable>
                    ) : (
                        <Pressable
                            onPress={send}
                            disabled={!canSend}
                            style={[
                                styles.action,
                                {
                                    backgroundColor: canSend
                                        ? theme.primary
                                        : theme.muted,
                                },
                            ]}
                            accessibilityRole="button"
                            accessibilityLabel="Send"
                        >
                            <Feather
                                name="arrow-up"
                                size={17}
                                color={
                                    canSend
                                        ? theme.primaryForeground
                                        : theme.weak
                                }
                            />
                        </Pressable>
                    )}
                </View>
            </View>
            <ImagePreview
                uri={previewUri}
                onClose={() => setPreviewUri(null)}
            />
            {showDisclaimer ? (
                <Text style={[styles.disclaimer, { color: theme.weakStrong }]}>
                    Nova can make mistakes. Check important information.
                </Text>
            ) : null}
            </View>
    );
}

const styles = StyleSheet.create({
    wrapper: {
        paddingHorizontal: 12,
        paddingTop: 8,
    },
    shell: {
        borderRadius: chatMetrics.composerRadius,
        borderWidth: StyleSheet.hairlineWidth,
        padding: chatMetrics.composerPadding,
    },
    contextBar: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        paddingHorizontal: 2,
        paddingBottom: 6,
    },
    contextLeft: {
        flex: 1,
        flexDirection: "row",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 6,
    },
    readOnlyChip: {
        opacity: 0.7,
    },
    modelChip: {
        flexShrink: 1,
        flexDirection: "row",
        alignItems: "center",
        gap: 4,
        borderRadius: 6,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 6,
        paddingVertical: 3,
        maxWidth: 150,
    },
    modelText: {
        flexShrink: 1,
        fontSize: 11.5,
    },
    agentChip: {
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        borderRadius: 6,
        paddingHorizontal: 8,
        paddingVertical: 3,
    },
    agentDot: {
        width: 6,
        height: 6,
        borderRadius: 3,
    },
    agentText: {
        fontSize: 12.5,
        fontWeight: "500",
    },
    contextText: {
        fontSize: 12,
        fontWeight: "600",
    },
    disclaimer: {
        marginTop: 8,
        textAlign: "center",
        fontSize: 11,
        lineHeight: 16,
    },
    input: {
        minHeight: chatMetrics.composerTextMinHeight,
        maxHeight: chatMetrics.composerTextMaxHeight,
        fontSize: chatMetrics.bodySize,
        lineHeight: chatMetrics.bodyLineHeight,
        paddingHorizontal: 4,
        paddingVertical: 6,
    },
    footer: {
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        marginTop: 8,
        paddingHorizontal: 2,
    },
    footerLeft: {
        flex: 1,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
    },
    addButton: {
        width: 30,
        height: 30,
        alignItems: "center",
        justifyContent: "center",
    },
    attachmentRow: {
        flexDirection: "row",
        gap: 8,
        paddingVertical: 6,
        paddingHorizontal: 2,
    },
    attachmentTile: {
        width: 56,
        height: 56,
        borderRadius: 8,
    },
    mentionRow: {
        flexDirection: "row",
        gap: 6,
        paddingVertical: 4,
        paddingHorizontal: 2,
    },
    mentionChip: {
        maxWidth: 170,
        borderRadius: 7,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 8,
        paddingVertical: 5,
    },
    mentionText: {
        fontSize: 12,
        fontWeight: "600",
    },
    attachmentImage: {
        width: 56,
        height: 56,
        borderRadius: 8,
    },
    documentChip: {
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        maxWidth: 190,
        height: 34,
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 8,
    },
    documentName: {
        flexShrink: 1,
        fontSize: 12,
    },
    attachmentRemove: {
        position: "absolute",
        top: -5,
        right: -5,
        width: 18,
        height: 18,
        borderRadius: 9,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
    },
    hint: {
        fontSize: 11,
    },
    voiceButton: {
        width: 28,
        height: 28,
        borderRadius: 14,
        marginRight: 6,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#1f1f1f",
    },
    action: {
        width: chatMetrics.composerControlSize,
        height: chatMetrics.composerControlSize,
        borderRadius: chatMetrics.composerControlSize / 2,
        alignItems: "center",
        justifyContent: "center",
    },
});
