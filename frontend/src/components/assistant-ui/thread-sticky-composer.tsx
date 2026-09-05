import { ArrowUpIcon, Square } from "lucide-react";
import {
    useEffect,
    useRef,
    type ClipboardEvent,
    type KeyboardEvent,
    type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import { useAui } from "@assistant-ui/react";

import type { NovaModelRecord, NovaProviderRecord } from "../../types/nova";
import { Button } from "../ui/button";
import { ComposerAddAttachment, ComposerAttachments } from "./attachment";
import { ModelSelector } from "./model-selector";
import { TodoProgressPanel } from "./todo-progress-panel";
import { WorkspaceControl } from "./workspace-control";

type ThreadStickyComposerProps = {
    composer: {
        ref: RefObject<HTMLTextAreaElement | null>;
        text: string;
        isRunning: boolean;
        onChange: (value: string) => void;
        onSubmit: () => void;
        onCancel: () => void;
        onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
    };
    modelSelection: {
        models: NovaModelRecord[];
        providers: NovaProviderRecord[];
        selectedModelId: string | null;
        onSelect: (modelId: string) => void;
        onModelsUpdated: (models: NovaModelRecord[]) => void;
        onProvidersRefresh: () => Promise<void>;
        onStatusChange: (message: string | null) => void;
    };
    workspace: {
        value: string | null;
        onChange: (path: string | null) => void;
    };
    onHeightChange?: (height: number) => void;
};

export function ThreadStickyComposer({
    composer,
    modelSelection,
    workspace,
    onHeightChange,
}: ThreadStickyComposerProps) {
    const { t } = useTranslation();
    const containerRef = useRef<HTMLDivElement | null>(null);
    const aui = useAui();

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

    useEffect(() => {
        const node = containerRef.current;
        if (!node || !onHeightChange) {
            return;
        }

        const reportHeight = () => {
            onHeightChange(node.offsetHeight);
        };

        reportHeight();

        const observer = new ResizeObserver(() => {
            reportHeight();
        });
        observer.observe(node);

        return () => {
            observer.disconnect();
            onHeightChange(0);
        };
    }, [onHeightChange]);

    return (
        <div
            ref={containerRef}
            className="pointer-events-none relative overflow-x-hidden pb-8 pt-3"
            style={{ scrollbarGutter: "stable" }}
        >
            <div className="pointer-events-none absolute inset-0 z-0 bg-gradient-to-t from-background via-background to-transparent" />
            <div className="relative z-10 mx-auto w-full max-w-(--thread-max-width) px-4">
                <TodoProgressPanel />
                <div className="pointer-events-auto relative rounded-(--composer-radius) border border-[#E4E3DF] bg-white p-3 shadow-[0_1px_2px_rgba(20,20,18,0.04),0_12px_32px_rgba(20,20,18,0.06)] transition-shadow focus-within:border-ring/75 focus-within:ring-2 focus-within:ring-ring/20">
                    <textarea
                        ref={composer.ref}
                        value={composer.text}
                        rows={1}
                        readOnly={composer.isRunning}
                        placeholder={t("composer.sendMessage")}
                        aria-label={t("composer.messageInput")}
                        className="max-h-40 min-h-10 w-full resize-none bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground/80 readOnly:cursor-default readOnly:opacity-60"
                        onChange={(event) =>
                            composer.onChange(event.target.value)
                        }
                        onKeyDown={composer.onKeyDown}
                        onPaste={handlePaste}
                    />

                    <ComposerAttachments />

                    <div className="mt-3 flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2">
                            <ComposerAddAttachment />
                            <WorkspaceControl
                                value={workspace.value}
                                onChange={workspace.onChange}
                            />
                        </div>
                        <div className="flex items-center gap-2">
                            <ModelSelector
                                compact
                                models={modelSelection.models}
                                providers={modelSelection.providers}
                                selectedModelId={modelSelection.selectedModelId}
                                onSelect={modelSelection.onSelect}
                                onModelsUpdated={modelSelection.onModelsUpdated}
                                onProvidersRefresh={
                                    modelSelection.onProvidersRefresh
                                }
                                onStatusChange={modelSelection.onStatusChange}
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
                                    disabled={composer.text.trim().length === 0}
                                    onClick={composer.onSubmit}
                                >
                                    <ArrowUpIcon className="size-4" />
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
