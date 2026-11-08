import Feather from "@expo/vector-icons/Feather";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
    FlatList,
    Pressable,
    StyleSheet,
    View,
    type LayoutChangeEvent,
    type NativeScrollEvent,
    type NativeSyntheticEvent,
} from "react-native";

import type { ApprovalRequest } from "../api/types";
import { useChat, type ChatMessage } from "../state/chat";
import { useTheme } from "../theme/useTheme";
import { MessageItem } from "./MessageItem";

const NEAR_BOTTOM = 80;

/** Stable empty list: a selector must not allocate on every store update. */
const EMPTY_MESSAGES: ChatMessage[] = [];

export const MessageList = memo(function MessageList({
    tabId,
    onRegenerate,
    approval,
}: {
    tabId: string;
    onRegenerate?: () => void;
    approval?: ApprovalRequest | null;
}) {
    // Only this subtree subscribes to the transcript, so a streamed token does
    // not re-render the composer, pickers or background panels.
    const messages = useChat(
        (state) => state.byId[tabId]?.messages ?? EMPTY_MESSAGES,
    );
    const { theme } = useTheme();
    const listRef = useRef<FlatList<ChatMessage>>(null);
    // Follow means "keep the newest content visible". It only changes while a
    // finger is on the list, so the growth caused by a stream cannot switch it
    // off the way an onScroll distance check would.
    const follow = useRef(true);
    const dragging = useRef(false);
    // A programmatic scroll can emit a momentum-end event on Android; only a
    // recent finger interaction may turn following off.
    const lastDragAt = useRef(0);
    const [away, setAway] = useState(false);
    // Measured sizes beat scrollToEnd(): its offset can stop short of the
    // content container's padding, and it runs before the last block settles.
    const contentHeight = useRef(0);
    const viewportHeight = useRef(0);
    const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
    const settle = useRef<ReturnType<typeof setTimeout> | null>(null);

    const scrollToEnd = useCallback(() => {
        const offset = Math.max(
            0,
            contentHeight.current - viewportHeight.current,
        );
        listRef.current?.scrollToOffset({ offset, animated: false });
    }, []);

    /**
     * Coalesce growth into one scroll per frame, then correct once more after
     * the stream goes quiet: markdown blocks and images settle a beat late.
     */
    const followToEnd = useCallback(() => {
        if (!follow.current) {
            return;
        }
        if (pending.current === null) {
            pending.current = setTimeout(() => {
                pending.current = null;
                if (follow.current) {
                    scrollToEnd();
                }
            }, 16);
        }
        if (settle.current !== null) {
            clearTimeout(settle.current);
        }
        settle.current = setTimeout(() => {
            settle.current = null;
            if (follow.current) {
                scrollToEnd();
            }
        }, 120);
    }, [scrollToEnd]);

    useEffect(
        () => () => {
            if (pending.current !== null) {
                clearTimeout(pending.current);
            }
            if (settle.current !== null) {
                clearTimeout(settle.current);
            }
        },
        [],
    );

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
            const row = (
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
            // FlatList's content-size callback can miss growth inside a
            // memoized cell (reasoning streams); the last row's own layout is
            // the direct signal that the transcript grew.
            return last ? (
                <View onLayout={followToEnd}>{row}</View>
            ) : (
                row
            );
        },
        [messages.length, onRegenerate, approval, followToEnd],
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
                    lastDragAt.current = Date.now();
                }}
                onScrollEndDrag={(event) => {
                    readPosition(event);
                    dragging.current = false;
                    lastDragAt.current = Date.now();
                }}
                onMomentumScrollEnd={(event) => {
                    if (Date.now() - lastDragAt.current < 1500) {
                        readPosition(event);
                    }
                    dragging.current = false;
                }}
                onContentSizeChange={(_width, height) => {
                    contentHeight.current = height;
                    followToEnd();
                }}
                onLayout={(event: LayoutChangeEvent) => {
                    viewportHeight.current = event.nativeEvent.layout.height;
                    followToEnd();
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
                        scrollToEnd();
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
