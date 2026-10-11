import { MenuIcon } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Thread } from "../../components/assistant-ui/thread";
import { Button } from "../../components/ui/button";
import { useMacHiddenTitlebar } from "../../lib/desktop-chrome";
import { DRAFT_THREAD_ID } from "../../lib/nova-constants";
import { readSendShortcut, shouldSendOnKeyDown } from "../../lib/ui-prefs";
import { useContextUsageStore } from "../../stores/context-usage-store";
import {
    selectIsRunning,
    useConversationStore,
} from "../../stores/conversation-store";
import type { NovaAgent, NovaModelRecord } from "../../types/nova";
import type { ModelOption } from "../../components/assistant-ui/elements/model-selector";

export interface NovaMainPanelProps {
    sidebarCollapsed: boolean;
    onExpandSidebar: () => void;
    composerRef: React.RefObject<HTMLTextAreaElement | null>;
    onComposerSubmit: () => void;
    onCancel: () => void;
    models: NovaModelRecord[];
    modelOptions: ModelOption[];
    selectedModelId: string | null;
    onSelectModel: (value: string) => void;
    reasoningEffort: string | null;
    onReasoningEffortChange: (effort: string) => void;
    agents: NovaAgent[];
    selectedAgentKey: string;
    onSelectAgent: (agentKey: string) => void;
    isNewChat: boolean;
    draftProjectName: string | null;
    onRemoveProject: () => void;
    sessionAgentKey: string | null;
    sessionProjectName: string | null;
    assistantName: string;
    assistantAgentKey: string | null;
    threadTitle: string | null;
}

/**
 * The center column: floating expand button when the sidebar is collapsed, and
 * the thread viewport with composer, model, and agent selectors.
 */
export function NovaMainPanel({
    sidebarCollapsed,
    onExpandSidebar,
    composerRef,
    onComposerSubmit,
    onCancel,
    models,
    modelOptions,
    selectedModelId,
    onSelectModel,
    reasoningEffort,
    onReasoningEffortChange,
    agents,
    selectedAgentKey,
    onSelectAgent,
    isNewChat,
    draftProjectName,
    onRemoveProject,
    sessionAgentKey,
    sessionProjectName,
    assistantName,
    assistantAgentKey,
    threadTitle,
}: NovaMainPanelProps) {
    const { t } = useTranslation();
    // Conversation run-state and selection come straight from the store, so the
    // shell no longer threads them through props on every streamed token.
    const isRunning = useConversationStore(selectIsRunning);
    const currentThreadId = useConversationStore(
        (state) => state.currentThreadId,
    );
    // macOS desktop only: keep the expand button clear of traffic lights.
    const macHiddenTitlebar = useMacHiddenTitlebar();
    // WorkBuddy-style main titlebar: conversation title plus drag space.
    const mainTitle = isNewChat ? t("threadList.newChat") : (threadTitle ?? "");
    // Drafts have no stored history, so the pill stays hidden there.
    const contextUsage = useContextUsageStore((state) =>
        currentThreadId === DRAFT_THREAD_ID
            ? undefined
            : state.bySession[currentThreadId],
    );

    // The four prop bundles handed to <Thread> are memoized so a commit that
    // only moves an unrelated field (e.g. a thread-title frame) doesn't rebuild
    // the composer/selector subtree that Thread memoizes on.
    const onComposerKeyDown = useCallback(
        (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
            if (shouldSendOnKeyDown(event, readSendShortcut())) {
                event.preventDefault();
                onComposerSubmit();
            }
        },
        [onComposerSubmit],
    );
    const composer = useMemo(
        () => ({
            isRunning,
            onSubmit: onComposerSubmit,
            onCancel,
            onKeyDown: onComposerKeyDown,
        }),
        [isRunning, onComposerSubmit, onCancel, onComposerKeyDown],
    );
    const modelSelection = useMemo(
        () => ({
            models,
            options: modelOptions,
            selectedModelId,
            onSelect: onSelectModel,
            effort: reasoningEffort,
            onEffortChange: onReasoningEffortChange,
        }),
        [
            models,
            modelOptions,
            selectedModelId,
            onSelectModel,
            reasoningEffort,
            onReasoningEffortChange,
        ],
    );
    const agentSelection = useMemo(
        () => ({ agents, selectedAgentKey, onSelect: onSelectAgent }),
        [agents, selectedAgentKey, onSelectAgent],
    );
    const contextBar = useMemo(
        () => ({
            isNewChat,
            draftProjectName,
            onRemoveProject,
            sessionAgentKey,
            sessionProjectName,
        }),
        [
            isNewChat,
            draftProjectName,
            onRemoveProject,
            sessionAgentKey,
            sessionProjectName,
        ],
    );

    return (
        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
            {macHiddenTitlebar ? (
                <div
                    className={
                        sidebarCollapsed
                            ? "pywebview-drag-region flex h-10 w-full shrink-0 items-center gap-2 pl-[132px] pr-4"
                            : "pywebview-drag-region flex h-10 w-full shrink-0 items-center gap-2 px-4"
                    }
                >
                    <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-[-0.01em]">
                        {mainTitle}
                    </h1>
                </div>
            ) : null}
            {sidebarCollapsed ? (
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className={
                        macHiddenTitlebar
                            ? "fixed left-[84px] top-0.5 z-30 rounded-full border border-border bg-card shadow-[0_8px_24px_rgba(20,20,18,0.07)]"
                            : "fixed left-4 top-4 z-30 rounded-full border border-border bg-card shadow-[0_8px_24px_rgba(20,20,18,0.07)]"
                    }
                    aria-label={t("app.expandSidebar")}
                    onClick={onExpandSidebar}
                >
                    <MenuIcon className="size-4" />
                </Button>
            ) : null}

            <div className="flex min-h-0 flex-1 flex-col">
                <Thread
                    composerRef={composerRef}
                    composer={composer}
                    modelSelection={modelSelection}
                    agentSelection={agentSelection}
                    contextBar={contextBar}
                    assistantName={assistantName}
                    assistantAgentKey={assistantAgentKey}
                    contextUsage={contextUsage ?? null}
                />
            </div>
        </main>
    );
}
