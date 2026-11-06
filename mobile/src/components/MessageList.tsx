import Feather from "@expo/vector-icons/Feather";
import { memo, useCallback, useRef, useState } from "react";
import {
    FlatList,
    Pressable,
    StyleSheet,
    View,
    type NativeScrollEvent,
    type NativeSyntheticEvent,
} from "react-native";

import type { ApprovalRequest } from "../api/types";
import type { ChatMessage } from "../state/chat";
import { useTheme } from "../theme/useTheme";
import { MessageItem } from "./MessageItem";

const NEAR_BOTTOM = 80;

export const MessageList = memo(function MessageList({
    messages,
    onRegenerate,
    approval,
}: {
    messages: ChatMessage[];
    onRegenerate?: () => void;
    approval?: ApprovalRequest | null;
}) {
    const { theme } = useTheme();
    const listRef = useRef<FlatList<ChatMessage>>(null);
    // Follow means "keep the newest content visible". It only changes while a
    // finger is on the list, so the growth caused by a stream cannot switch it
    // off the way an onScroll distance check would.
    const follow = useRef(true);
    const dragging = useRef(false);
    const [away, setAway] = useState(false);

    const scrollToEnd = useCallback(() => {
        listRef.current?.scrollToEnd({ animated: false });
    }, []);

    const readPosition = useCallback(
        (event: NativeSyntheticEvent<NativeScrollEvent>) => {
            const { contentOffset, contentSize, layoutMeasurement } =
                event.nativeEvent;
            const distance =
                contentSize.height -
                (contentOffset.y + layoutMeasurement.height);
            const next = distance >= NEAR_BOTTOM;
            follow.current = !next;
            setAway(next);
        },
        [],
    );

    const onScroll = useCallback(
        (event: NativeSyntheticEvent<NativeScrollEvent>) => {
            if (!dragging.current) {
                return;
            }
            readPosition(event);
        },
        [readPosition],
    );

    const renderItem = useCallback(
        ({ item, index }: { item: ChatMessage; index: number }) => {
            const last = index === messages.length - 1;
            return (
                <MessageItem
                    message={item}
                    isLast={last}
                    approval={approval}
                    onRegenerate={
                        last && item.role === "assistant"
                            ? onRegenerate
                            : undefined
                    }
                />
            );
        },
        [messages.length, onRegenerate, approval],
    );

    return (
        <View style={styles.wrapper}>
            <FlatList
                ref={listRef}
                data={messages}
                keyExtractor={(item) => item.id}
                renderItem={renderItem}
                onScroll={onScroll}
                scrollEventThrottle={32}
                onScrollBeginDrag={() => {
                    dragging.current = true;
                }}
                onScrollEndDrag={(event) => {
                    readPosition(event);
                    dragging.current = false;
                }}
                onMomentumScrollEnd={(event) => {
                    readPosition(event);
                    dragging.current = false;
                }}
                onContentSizeChange={() => {
                    if (follow.current) {
                        scrollToEnd();
                    }
                }}
                onLayout={() => {
                    if (follow.current) {
                        scrollToEnd();
                    }
                }}
                keyboardDismissMode="interactive"
                keyboardShouldPersistTaps="handled"
                style={styles.list}
                showsVerticalScrollIndicator={false}
                contentContainerStyle={styles.content}
                initialNumToRender={12}
                maxToRenderPerBatch={12}
                windowSize={11}
                removeClippedSubviews={false}
            />
            {away ? (
                <Pressable
                    onPress={() => {
                        follow.current = true;
                        setAway(false);
                        listRef.current?.scrollToEnd({ animated: true });
                    }}
                    style={[
                        styles.jump,
                        {
                            backgroundColor: theme.card,
                            borderColor: theme.border,
                        },
                    ]}
                    accessibilityRole="button"
                    accessibilityLabel="Scroll to bottom"
                >
                    <Feather
                        name="arrow-down"
                        size={17}
                        color={theme.weakStrong}
                    />
                </Pressable>
            ) : null}
        </View>
    );
});

const styles = StyleSheet.create({
    wrapper: {
        flex: 1,
    },
    list: {
        flex: 1,
    },
    jump: {
        position: "absolute",
        alignSelf: "center",
        bottom: 12,
        width: 36,
        height: 36,
        borderRadius: 18,
        borderWidth: StyleSheet.hairlineWidth,
        alignItems: "center",
        justifyContent: "center",
    },
    content: {
        paddingHorizontal: 16,
        paddingTop: 24,
        paddingBottom: 24,
    },
});
