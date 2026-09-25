import { MenuIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Thread } from "../../components/assistant-ui/thread";
import { Button } from "../../components/ui/button";
import type { NovaAgent, NovaModelRecord } from "../../types/nova";

export interface NovaMainPanelProps {
    sidebarCollapsed: boolean;
    onExpandSidebar: () => void;
    composerRef: React.RefObject<HTMLTextAreaElement | null>;
    composerText: string;
    isRunning: boolean;
    onComposerChange: (text: string) => void;
    onComposerSubmit: () => void;
    onCancel: () => void;
    models: NovaModelRecord[];
    selectedModelId: string | null;
    onSelectModel: (value: string) => void;
    agents: NovaAgent[];
    selectedAgentKey: string;
    onSelectAgent: (agentKey: string) => void;
    isNewChat: boolean;
    draftProjectName: string | null;
    onRemoveProject: () => void;
    sessionAgentKey: string | null;
    sessionProjectName: string | null;
}

/**
 * The center column: floating expand button when the sidebar is collapsed, and
 * the thread viewport with composer, model, and agent selectors.
 */
export function NovaMainPanel({
    sidebarCollapsed,
    onExpandSidebar,
    composerRef,
    composerText,
    isRunning,
    onComposerChange,
    onComposerSubmit,
    onCancel,
    models,
    selectedModelId,
    onSelectModel,
    agents,
    selectedAgentKey,
    onSelectAgent,
    isNewChat,
    draftProjectName,
    onRemoveProject,
    sessionAgentKey,
    sessionProjectName,
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
                    composer={{
                        ref: composerRef,
                        text: composerText,
                        isRunning,
                        onChange: onComposerChange,
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
                        selectedModelId,
                        onSelect: onSelectModel,
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
                />
            </div>
        </main>
    );
}
