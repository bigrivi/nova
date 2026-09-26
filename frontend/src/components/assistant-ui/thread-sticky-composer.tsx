import { ArrowUpIcon, Square } from "lucide-react";
import {
    type ClipboardEvent,
    type KeyboardEvent,
    useLayoutEffect,
    type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import { useAui } from "@assistant-ui/react";

import { useComposerStore } from "../../stores/composer-store";
import type { NovaAgent, NovaModelRecord } from "../../types/nova";
import { Button } from "../ui/button";
import { BackgroundTasksPanel } from "./background-tasks-panel";
import { ComposerAddAttachment, ComposerAttachments } from "./attachment";
import {
    ComposerContextBar,
    type ComposerContextBarProps,
} from "./composer-context-bar";
import { ModelSelector } from "./model-selector";
import { TodoProgressPanel } from "./todo-progress-panel";

export type ThreadComposerContextBarProps = Omit<
    ComposerContextBarProps,
    "agents" | "selectedAgentKey" | "onSelectAgent"
>;

type ThreadStickyComposerProps = {
    composerRef: RefObject<HTMLTextAreaElement | null>;
    composer: {
        isRunning: boolean;
        onSubmit: () => void;
        onCancel: () => void;
        onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
    };
    modelSelection: {
        models: NovaModelRecord[];
        selectedModelId: string | null;
        onSelect: (modelId: string) => void;
    };
    agentSelection: {
        agents: NovaAgent[];
        selectedAgentKey: string | null;
        onSelect: (agentKey: string) => void;
    };
    contextBar: ThreadComposerContextBarProps;
    showDisclaimer?: boolean;
};

export function ThreadStickyComposer({
    composerRef,
    composer,
    modelSelection,
    agentSelection,
    contextBar,
    showDisclaimer = false,
}: ThreadStickyComposerProps) {
    const { t } = useTranslation();
    const aui = useAui();
    const text = useComposerStore((state) => state.text);
    const setText = useComposerStore((state) => state.setText);

    // Auto-size reads the draft here, so a keystroke re-renders the composer
    // alone instead of the whole shell.
    useLayoutEffect(() => {
        const textarea = composerRef.current;
        if (!textarea) {
            return;
        }
        textarea.style.height = "0px";
        textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
    }, [composerRef, text]);

    const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
        const imageFiles = Array.from(event.clipboardData.items)
            .filter(
                (item) =>
                    item.kind === "file" && item.type.startsWith("image/"),
            )
            .map((item) => item.getAsFile())
            .filter((file): file is File => file !== null);

        if (imageFiles.length === 0) {
            return;
        }
        event.preventDefault();
        for (const file of imageFiles) {
            aui.composer()?.addAttachment(file);
        }
    };

    return (
        <div className="pointer-events-none relative overflow-x-clip pb-2 pt-3">
            <div className="pointer-events-none absolute inset-0 z-0 bg-gradient-to-t from-background via-background to-transparent" />
            <div className="relative z-10 w-full">
                <BackgroundTasksPanel />
                <TodoProgressPanel />
                <div className="pointer-events-auto relative rounded-(--composer-radius) border border-[#E4E3DF] bg-white p-3 shadow-[0_4px_24px_rgba(20,20,18,0.04)] transition-[box-shadow,border-color] focus-within:border-ring/75">
                    <ComposerContextBar
                        isNewChat={contextBar.isNewChat}
                        agents={agentSelection.agents}
                        selectedAgentKey={agentSelection.selectedAgentKey}
                        onSelectAgent={agentSelection.onSelect}
                        sessionAgentKey={contextBar.sessionAgentKey}
                        draftProjectName={contextBar.draftProjectName}
                        sessionProjectName={contextBar.sessionProjectName}
                        onRemoveProject={contextBar.onRemoveProject}
                    />
                    <textarea
                        ref={composerRef}
                        value={text}
                        rows={1}
                        readOnly={composer.isRunning}
                        placeholder={t("composer.sendMessage")}
                        aria-label={t("composer.messageInput")}
                        className="max-h-40 min-h-10 w-full resize-none bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground/80 readOnly:cursor-default readOnly:opacity-60"
                        onChange={(event) => setText(event.target.value)}
                        onKeyDown={composer.onKeyDown}
                        onPaste={handlePaste}
                    />

                    <ComposerAttachments />

                    <div className="mt-3 flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                            <ComposerAddAttachment />
                        </div>
                        <div className="flex items-center gap-2">
                            <ModelSelector
                                models={modelSelection.models}
                                selectedModelId={modelSelection.selectedModelId}
                                onSelect={modelSelection.onSelect}
                            />

                            {composer.isRunning ? (
                                <Button
                                    type="button"
                                    size="icon"
                                    className="rounded-full"
                                    onClick={composer.onCancel}
                                >
                                    <Square className="size-4 fill-current" />
                                </Button>
                            ) : (
                                <Button
                                    type="button"
                                    size="icon"
                                    className="rounded-full transition-colors hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"
                                    disabled={text.trim().length === 0}
                                    onMouseDown={(event) =>
                                        event.preventDefault()
                                    }
                                    onClick={composer.onSubmit}
                                >
                                    <ArrowUpIcon className="size-4" />
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
                {showDisclaimer ? (
                    <p className="mt-2 text-center text-[11px] leading-normal text-muted-foreground">
                        {t("composer.aiDisclaimer")}
                    </p>
                ) : null}
            </div>
        </div>
    );
}
