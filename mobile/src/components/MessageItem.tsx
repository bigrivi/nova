import Feather from "@expo/vector-icons/Feather";
import * as Clipboard from "expo-clipboard";
import { memo, useMemo, useState } from "react";
import {
    Image,
    Pressable,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { buildTimelineItems, parseSubagentMessage } from "../chat/presentation";
import type { ChatMessage, ChatPart } from "../state/chat";
import { chatMetrics } from "../theme/tokens";
import { useTheme } from "../theme/useTheme";
import { ImagePreview } from "./ImagePreview";
import { MarkdownMessage } from "./MarkdownMessage";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { StandaloneToolCard, ThinkingChain } from "./ToolCard";

function Avatar() {
    const { theme } = useTheme();
    return (
        <View
            style={[
                styles.avatar,
                { backgroundColor: theme.brandSoft },
            ]}
        >
            <Text style={[styles.avatarText, { color: theme.brand }]}>N</Text>
        </View>
    );
}

function FailureNotice({ text }: { text: string }) {
    const { theme } = useTheme();
    return (
        <View
            style={[
                styles.failure,
                {
                    backgroundColor: theme.dangerSoft,
                    borderColor: theme.danger,
                },
            ]}
        >
            <Feather name="alert-triangle" size={15} color={theme.danger} />
            <Text style={[styles.failureText, { color: theme.danger }]}>
                {text.replace(/^\[error\]\s*/, "")}
            </Text>
        </View>
    );
}

function AssistantText({
    text,
    streaming,
}: {
    text: string;
    streaming: boolean;
}) {
    if (text.startsWith("[error] ")) {
        return <FailureNotice text={text} />;
    }
    return <MarkdownMessage text={text} streaming={streaming} />;
}

function AssistantMessage({
    message,
    isLast,
}: {
    message: ChatMessage;
    isLast: boolean;
}) {
    const { theme } = useTheme();
    const streaming = message.status === "streaming";
    const items = useMemo(
        () => buildTimelineItems(message.parts),
        [message.parts],
    );
    const copyText = useMemo(
        () =>
            message.parts
                .filter((part): part is Extract<ChatPart, { type: "text" }> =>
                    part.type === "text",
                )
                .map((part) => part.text)
                .join("\n"),
        [message.parts],
    );

    // The web inserts an `indicator` part while the assistant is running with
    // no content to show. Reproduce that: no parts, a completed reasoning
    // block, or a settled tool call all mean the model is thinking again.
    const lastPart = message.parts[message.parts.length - 1];
    const waiting =
        streaming &&
        (!lastPart ||
            (lastPart.type === "text" && lastPart.text.trim() === "") ||
            (lastPart.type === "reasoning" && lastPart.completed) ||
            (lastPart.type === "tool-call" && lastPart.status !== "running"));
    const showIndicator = streaming && (waiting || message.retry != null);

    return (
        <View style={styles.assistant}>
            <View style={styles.assistantHeader}>
                <Avatar />
                <Text style={[styles.agentName, { color: theme.weakStrong }]}>
                    Nova
                </Text>
            </View>

            {items.map((item) => {
                if (item.kind === "text") {
                    const part = message.parts[item.index];
                    if (!part || part.type !== "text") {
                        return null;
                    }
                    return (
                        <View key={`text-${item.index}`}>
                            <AssistantText
                                text={part.text}
                                streaming={streaming}
                            />
                        </View>
                    );
                }
                if (item.kind === "chain") {
                    return (
                        <ThinkingChain
                            key={`chain-${item.indices[0]}`}
                            parts={message.parts}
                            item={item}
                            streaming={streaming}
                        />
                    );
                }
                const part = message.parts[item.index];
                if (!part || part.type !== "tool-call") {
                    return null;
                }
                return (
                    <StandaloneToolCard
                        key={`tool-${part.toolCallId}`}
                        part={part}
                    />
                );
            })}

            {showIndicator ? (
                <ThinkingIndicator retry={message.retry ?? null} />
            ) : null}

            {message.error ? (
                <View
                    style={[
                        styles.messageError,
                        {
                            backgroundColor: theme.dangerSoft,
                            borderColor: theme.danger,
                        },
                    ]}
                >
                    <Text style={[styles.messageErrorText, { color: theme.danger }]}>
                        {message.error}
                    </Text>
                </View>
            ) : null}

            {!streaming && isLast && copyText ? (
                <Pressable
                    onPress={() => void Clipboard.setStringAsync(copyText)}
                    style={styles.copyButton}
                    accessibilityRole="button"
                    accessibilityLabel="Copy answer"
                >
                    <Feather name="copy" size={13} color={theme.weak} />
                    <Text style={[styles.copyText, { color: theme.weak }]}>
                        Copy
                    </Text>
                </Pressable>
            ) : null}
        </View>
    );
}

function UserImage({ uri }: { uri: string }) {
    const [open, setOpen] = useState(false);
    return (
        <>
            <Pressable
                onPress={() => setOpen(true)}
                accessibilityRole="imagebutton"
                accessibilityLabel="Preview attached image"
            >
                <Image source={{ uri }} style={styles.userImage} />
            </Pressable>
            <ImagePreview
                uri={open ? uri : null}
                onClose={() => setOpen(false)}
            />
        </>
    );
}

function UserMessage({ message }: { message: ChatMessage }) {
    const { theme } = useTheme();
    const text = message.parts
        .filter((part): part is Extract<ChatPart, { type: "text" }> =>
            part.type === "text",
        )
        .map((part) => part.text)
        .join("\n");

    const attachments = message.attachments ?? [];
    const images = attachments.filter(
        (item): item is { kind: "image"; uri: string; name: string } =>
            item.kind === "image" && typeof item.uri === "string",
    );
    const documents = attachments.filter(
        (item) => item.kind === "document",
    );
    const hasText = text.trim().length > 0;

    if (message.variant === "subagent") {
        const parsed = parseSubagentMessage(text);
        const failed = parsed?.status === "error";
        return (
            <View
                style={[
                    styles.subagent,
                    {
                        backgroundColor: failed
                            ? theme.dangerSoft
                            : theme.muted,
                        borderColor: failed ? theme.danger : theme.border,
                    },
                ]}
            >
                <Text style={[styles.subagentTitle, { color: theme.foreground }]}>
                    Sub-agent {parsed?.target ?? ""}
                </Text>
                <Text style={[styles.subagentBody, { color: theme.weakStrong }]}>
                    {parsed?.body ?? text}
                </Text>
            </View>
        );
    }

    return (
        <View style={styles.userRow}>
            {images.length > 0 ? (
                <View style={styles.userImages}>
                    {images.map((image, index) => (
                        <UserImage
                            key={`${image.uri}-${index}`}
                            uri={image.uri}
                        />
                    ))}
                </View>
            ) : null}
            {documents.length > 0 ? (
                <View style={styles.userDocuments}>
                    {documents.map((document, index) => (
                        <View
                            key={`${document.name}-${index}`}
                            style={[
                                styles.userDocument,
                                {
                                    backgroundColor: theme.muted,
                                    borderColor: theme.border,
                                },
                            ]}
                        >
                            <Feather
                                name="file-text"
                                size={13}
                                color={theme.weakStrong}
                            />
                            <Text
                                numberOfLines={1}
                                style={[
                                    styles.userDocumentName,
                                    { color: theme.weakStrong },
                                ]}
                            >
                                {document.name}
                            </Text>
                        </View>
                    ))}
                </View>
            ) : null}
            {hasText ? (
                <View
                    style={[
                        styles.userBubble,
                        {
                            backgroundColor: theme.userBubble,
                            borderColor: theme.userBubbleBorder,
                        },
                    ]}
                >
                    <Text
                        selectable
                        style={[
                            styles.userText,
                            { color: theme.foreground },
                        ]}
                    >
                        {text}
                    </Text>
                </View>
            ) : null}
        </View>
    );
}

export const MessageItem = memo(function MessageItem({
    message,
    isLast,
}: {
    message: ChatMessage;
    isLast: boolean;
}) {
    return message.role === "user" ? (
        <UserMessage message={message} />
    ) : (
        <AssistantMessage message={message} isLast={isLast} />
    );
});

const styles = StyleSheet.create({
    assistant: {
        gap: 8,
        marginBottom: 8,
    },
    assistantHeader: {
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
    },
    avatar: {
        width: chatMetrics.assistantAvatar,
        height: chatMetrics.assistantAvatar,
        borderRadius: chatMetrics.assistantAvatar / 2,
        alignItems: "center",
        justifyContent: "center",
    },
    avatarText: {
        fontSize: 12,
        fontWeight: "700",
    },
    agentName: {
        fontSize: 12,
        fontWeight: "500",
    },
    userRow: {
        alignItems: "flex-end",
        gap: 6,
        marginBottom: 8,
    },
    userImages: {
        flexDirection: "row",
        flexWrap: "wrap",
        justifyContent: "flex-end",
        gap: 6,
        maxWidth: "82%",
    },
    userImage: {
        width: 64,
        height: 64,
        borderRadius: 9,
    },
    userDocuments: {
        alignItems: "flex-end",
        gap: 4,
        maxWidth: "82%",
    },
    userDocument: {
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        maxWidth: 220,
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: 8,
        paddingVertical: 5,
    },
    userDocumentName: {
        flexShrink: 1,
        fontSize: 12,
    },
    userBubble: {
        maxWidth: `${chatMetrics.userBubbleMaxWidthRatio * 100}%`,
        borderRadius: chatMetrics.userBubbleRadius,
        borderWidth: StyleSheet.hairlineWidth,
        paddingHorizontal: chatMetrics.userBubblePaddingX,
        paddingVertical: chatMetrics.userBubblePaddingY,
    },
    userText: {
        fontSize: chatMetrics.bodySize,
        lineHeight: chatMetrics.bodyLineHeight,
    },
    subagent: {
        borderRadius: 10,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 10,
        marginBottom: 8,
        gap: 4,
    },
    subagentTitle: {
        fontSize: 12,
        fontWeight: "600",
    },
    subagentBody: {
        fontSize: 13,
        lineHeight: 20,
    },
    messageError: {
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 10,
    },
    messageErrorText: {
        fontSize: 13,
        lineHeight: 19,
    },
    failure: {
        flexDirection: "row",
        gap: 8,
        borderRadius: 8,
        borderWidth: StyleSheet.hairlineWidth,
        padding: 10,
    },
    failureText: {
        flex: 1,
        fontSize: 13,
        lineHeight: 19,
    },
    copyButton: {
        flexDirection: "row",
        alignItems: "center",
        gap: 5,
        alignSelf: "flex-start",
        paddingVertical: 4,
        paddingRight: 8,
    },
    copyText: {
        fontSize: 12,
    },
});
