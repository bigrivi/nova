import { MenuIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Thread } from "../../components/assistant-ui/thread";
import { Button } from "../../components/ui/button";
import type { NovaAgent, NovaModelRecord } from "../../types/nova";
import type { ModelOption } from "../../components/assistant-ui/elements/model-selector";

export interface NovaMainPanelProps {
    sidebarCollapsed: boolean;
    onExpandSidebar: () => void;
    composerRef: React.RefObject<HTMLTextAreaElement | null>;
    isRunning: boolean;
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
}

/**
 * The center column: floating expand button when the sidebar is collapsed, and
 * the thread viewport with composer, model, and agent selectors.
 */
export function NovaMainPanel({
    sidebarCollapsed,
    onExpandSidebar,
    composerRef,
    isRunning,
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
}: NovaMainPanelProps) {
    const { t } = useTranslation();

    return (
        <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
            {sidebarCollapsed ? (
                <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="fixed left-4 top-4 z-30 rounded-full border border-[#E4E3DF] bg-white shadow-[0_8px_24px_rgba(20,20,18,0.07)]"
                    aria-label={t("app.expandSidebar")}
                    onClick={onExpandSidebar}
                >
                    <MenuIcon className="size-4" />
                </Button>
            ) : null}

            <div className="flex min-h-0 flex-1 flex-col">
                <Thread
                    composerRef={composerRef}
                    composer={{
                        isRunning,
                        onSubmit: onComposerSubmit,
                        onCancel,
                        onKeyDown: (event) => {
                            if (event.key === "Enter" && !event.shiftKey) {
                                event.preventDefault();
                                onComposerSubmit();
                            }
                        },
                    }}
                    modelSelection={{
                        models,
                        options: modelOptions,
                        selectedModelId,
                        onSelect: onSelectModel,
                        effort: reasoningEffort,
                        onEffortChange: onReasoningEffortChange,
                    }}
                    agentSelection={{
                        agents,
                        selectedAgentKey,
                        onSelect: onSelectAgent,
                    }}
                    contextBar={{
                        isNewChat,
                        draftProjectName,
                        onRemoveProject,
                        sessionAgentKey,
                        sessionProjectName,
                    }}
                    assistantName={assistantName}
                    assistantAgentKey={assistantAgentKey}
                />
            </div>
        </main>
    );
}
