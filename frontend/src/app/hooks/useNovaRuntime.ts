import { useCallback } from "react";

import type { ThreadMessageLike } from "@assistant-ui/react";
import {
    AuiConfig,
    CompositeAttachmentAdapter,
    SimpleImageAttachmentAdapter,
    SimpleTextAttachmentAdapter,
    Tools,
    useExternalStoreRuntime,
} from "@assistant-ui/react";

import { toolkit } from "../../components/assistant-ui/toolkit";
import { useComposerStore } from "../../stores/composer-store";
import {
    selectActiveThreadListId,
    selectIsRunning,
    useConversationStore,
} from "../../stores/conversation-store";
import type { NovaAttachmentData } from "../../types/nova";

/** Stable empty buffer so an empty thread never churns the runtime's input. */
const EMPTY_MESSAGES: ThreadMessageLike[] = [];

/**
 * Stable identity converter. The library compares `convertMessage` by reference
 * to decide whether a store update is cheap (same messages + isRunning) or a
 * full re-conversion; a fresh arrow function here would flush that cache on every
 * adapter sync and regenerate the pre-first-token loading placeholder, making a
 * title-frame update flash the loading indicator. Keep this at module scope.
 */
const passthroughMessage = (message: ThreadMessageLike) => message;

const attachmentsAdapter = new CompositeAttachmentAdapter([
    new SimpleImageAttachmentAdapter(),
    new SimpleTextAttachmentAdapter(),
]);

/** Tools are registry-bound (`toolkit` is a module constant), so build once. */
const config = AuiConfig({ tools: Tools({ toolkit }) });

export interface NovaRuntimeDeps {
    setThreadMessages: (threadId: string, messages: ThreadMessageLike[]) => void;
    submitPrompt: (
        prompt: string,
        attachments?: NovaAttachmentData[],
    ) => Promise<void>;
    handleCancel: (threadId?: string) => Promise<void>;
    switchToDraftThread: (projectId?: string | null) => void;
    selectThread: (threadId: string) => void;
    handleRenameThread: (threadId: string, newTitle: string) => Promise<void>;
    handleDeleteThread: (threadId: string) => Promise<void>;
}

/**
 * Assemble the assistant-ui external-store runtime and the tool registry, and
 * own `handleComposerSubmit` which bridges runtime-managed attachments with the
 * conversation's `submitPrompt`.
 */
export function useNovaRuntime(deps: NovaRuntimeDeps) {
    const {
        setThreadMessages,
        submitPrompt,
        handleCancel: cancelThread,
        switchToDraftThread,
        selectThread,
        handleRenameThread,
        handleDeleteThread,
    } = deps;

    // Conversation state is read straight from the store; only the action
    // callbacks still arrive as deps, so the runtime no longer depends on the
    // shell to thread five state fields through on every render.
    const currentThreadId = useConversationStore(
        (state) => state.currentThreadId,
    );
    const currentMessages =
        useConversationStore(
            (state) => state.messagesByThreadId[state.currentThreadId],
        ) ?? EMPTY_MESSAGES;
    const isRunning = useConversationStore(selectIsRunning);
    const threads = useConversationStore((state) => state.threads);
    const activeThreadListId = useConversationStore(selectActiveThreadListId);

    const onCancel = useCallback(() => {
        return cancelThread();
    }, [cancelThread]);
    const setMessages = useCallback(
        (messages: readonly ThreadMessageLike[]) => {
            setThreadMessages(currentThreadId, [...messages]);
        },
        [setThreadMessages, currentThreadId],
    );
    const onResumeToolCall = useCallback(
        (options: { payload?: unknown }) => {
            void submitPrompt(String(options.payload ?? ""));
        },
        [submitPrompt],
    );

    const runtime = useExternalStoreRuntime({
        messages: currentMessages,
        isRunning,
        onNew: async () => {},
        onCancel,
        convertMessage: passthroughMessage,
        setMessages,
        onResumeToolCall,
        adapters: {
            attachments: attachmentsAdapter,
            threadList: {
                threadId: activeThreadListId,
                threads,
                archivedThreads: [],
                onSwitchToNewThread: switchToDraftThread,
                onSwitchToThread: selectThread,
                onRename: handleRenameThread,
                onDelete: handleDeleteThread,
            },
        },
    });

    async function handleComposerSubmit() {
        const prompt = useComposerStore.getState().text.trim();
        if (!prompt || isRunning) {
            return;
        }
        const composerState = runtime.thread.composer.getState();
        const pendingAttachments = composerState.attachments;

        let processedAttachments: NovaAttachmentData[] | undefined;
        if (pendingAttachments.length > 0) {
            processedAttachments = [];
            for (const att of pendingAttachments) {
                if (att.status.type === "complete" && att.content) {
                    processedAttachments.push(att as NovaAttachmentData);
                } else if (att.status.type === "requires-action" && att.file) {
                    const result = await attachmentsAdapter.send(
                        att as unknown as Parameters<
                            typeof attachmentsAdapter.send
                        >[0],
                    );
                    processedAttachments.push(result as NovaAttachmentData);
                }
            }
            runtime.thread.composer.clearAttachments();
        }

        await deps.submitPrompt(prompt, processedAttachments);
    }

    return { runtime, config, handleComposerSubmit };
}
