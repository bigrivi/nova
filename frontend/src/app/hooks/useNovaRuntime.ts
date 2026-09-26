import type { ThreadMessageLike } from "@assistant-ui/react";
import {
    CompositeAttachmentAdapter,
    SimpleImageAttachmentAdapter,
    SimpleTextAttachmentAdapter,
    Tools,
    useAui,
    useExternalStoreRuntime,
} from "@assistant-ui/react";

import { toolkit } from "../../components/assistant-ui/toolkit";
import { useComposerStore } from "../../stores/composer-store";
import type { NovaAttachmentData, NovaThreadSummary } from "../../types/nova";

export interface NovaRuntimeDeps {
    currentMessages: ThreadMessageLike[];
    isRunning: boolean;
    currentThreadId: string;
    threads: NovaThreadSummary[];
    activeThreadListId: string | undefined;
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
    const runtime = useExternalStoreRuntime({
        messages: deps.currentMessages,
        isRunning: deps.isRunning,
        onNew: async () => {},
        onCancel: () => deps.handleCancel(),
        convertMessage: (message) => message,
        setMessages: (messages) => {
            deps.setThreadMessages(deps.currentThreadId, [...messages]);
        },
        onResumeToolCall: (options) => {
            void deps.submitPrompt(String(options.payload ?? ""));
        },
        adapters: {
            attachments: new CompositeAttachmentAdapter([
                new SimpleImageAttachmentAdapter(),
                new SimpleTextAttachmentAdapter(),
            ]),
            threadList: {
                threadId: deps.activeThreadListId,
                threads: deps.threads,
                archivedThreads: [],
                onSwitchToNewThread: deps.switchToDraftThread,
                onSwitchToThread: (threadId) => {
                    deps.selectThread(threadId);
                },
                onRename: (threadId, newTitle) =>
                    deps.handleRenameThread(threadId, newTitle),
                onDelete: (threadId) => deps.handleDeleteThread(threadId),
            },
        },
    });

    const aui = useAui({ tools: Tools({ toolkit }) });

    async function handleComposerSubmit() {
        const prompt = useComposerStore.getState().text.trim();
        if (!prompt || deps.isRunning) {
            return;
        }
        const composerState = runtime.thread.composer.getState();
        const pendingAttachments = composerState.attachments;

        let processedAttachments: NovaAttachmentData[] | undefined;
        if (pendingAttachments.length > 0) {
            const adapter = new CompositeAttachmentAdapter([
                new SimpleImageAttachmentAdapter(),
                new SimpleTextAttachmentAdapter(),
            ]);
            processedAttachments = [];
            for (const att of pendingAttachments) {
                if (att.status.type === "complete" && att.content) {
                    processedAttachments.push(att as NovaAttachmentData);
                } else if (att.status.type === "requires-action" && att.file) {
                    const result = await adapter.send(
                        att as unknown as Parameters<typeof adapter.send>[0],
                    );
                    processedAttachments.push(result as NovaAttachmentData);
                }
            }
            runtime.thread.composer.clearAttachments();
        }

        await deps.submitPrompt(prompt, processedAttachments);
    }

    return { runtime, aui, handleComposerSubmit };
}
