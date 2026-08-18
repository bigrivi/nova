import { ApprovalDialog } from "@/components/assistant-ui/approval-dialog";
import { AskUserTool } from "@/components/assistant-ui/ask-user-tool";
import { useZoom } from "@/lib/use-zoom";
import { useApprovalStore } from "@/stores/approval-store";
import { useAskUserStore } from "@/stores/ask-user-store";
import type { NovaModelRecord, NovaProviderRecord } from "@/types/nova";
import { AuiIf, ThreadPrimitive } from "@assistant-ui/react";
import type { KeyboardEvent, RefObject } from "react";
import {
    type FC,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import { CompactionBanner } from "./thread-compaction-banner";
import { ThreadComposerContainer } from "./thread-composer";
import { ThreadMessage } from "./thread-message";
import { ThreadScrollToBottom } from "./thread-scroll-to-bottom";

type ThreadProps = {
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
};

export const Thread: FC<ThreadProps> = ({ composer, modelSelection }) => {
    const [composerHeight, setComposerHeight] = useState(0);
    const [askUserHeight, setAskUserHeight] = useState(0);
    const [approvalHeight, setApprovalHeight] = useState(0);
    const zoomTargetRef = useZoom();
    const activeCall = useAskUserStore((s) => s.active);
    const pendingApproval = useApprovalStore((s) => s.pending);

    const askUserObserverRef = useRef<ResizeObserver | null>(null);
    const approvalObserverRef = useRef<ResizeObserver | null>(null);

    const askUserRef = useCallback((el: HTMLDivElement | null) => {
        askUserObserverRef.current?.disconnect();
        askUserObserverRef.current = null;
        if (!el) {
            setAskUserHeight(0);
            return;
        }
        const ro = new ResizeObserver(([entry]) =>
            setAskUserHeight(entry.contentRect.height),
        );
        ro.observe(el);
        askUserObserverRef.current = ro;
    }, []);

    const approvalRef = useCallback((el: HTMLDivElement | null) => {
        approvalObserverRef.current?.disconnect();
        approvalObserverRef.current = null;
        if (!el) {
            setApprovalHeight(0);
            return;
        }
        const ro = new ResizeObserver(([entry]) =>
            setApprovalHeight(entry.contentRect.height),
        );
        ro.observe(el);
        approvalObserverRef.current = ro;
    }, []);

    useEffect(() => {
        return () => {
            askUserObserverRef.current?.disconnect();
            approvalObserverRef.current?.disconnect();
        };
    }, []);

    const spacerHeight = useMemo(() => {
        if (approvalHeight > 0) return approvalHeight + 16;
        if (askUserHeight > 0) return askUserHeight + 16;
        if (composerHeight > 0) return composerHeight + 20;
        return 0;
    }, [approvalHeight, askUserHeight, composerHeight]);

    return (
        <>
            <ThreadPrimitive.Root
                className="aui-root aui-thread-root @container relative flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background"
                style={{
                    ["--thread-max-width" as string]: "48rem",
                    ["--composer-radius" as string]: "24px",
                    ["--composer-padding" as string]: "10px",
                }}
            >
                <ThreadPrimitive.Viewport
                    autoScroll
                    data-slot="aui_thread-viewport"
                    turnAnchor="bottom"
                    className="relative flex min-h-0 flex-1 flex-col overflow-y-auto"
                    style={{ scrollbarGutter: "stable" }}
                >
                    <div className="mx-auto flex min-h-full w-full max-w-(--thread-max-width) flex-col px-4 pt-4">
                        <div data-slot="aui_message-group" className="mb-5">
                            <div
                                ref={zoomTargetRef}
                                className="flex flex-col gap-y-2 empty:hidden"
                            >
                                <ThreadPrimitive.Messages>
                                    {() => <ThreadMessage />}
                                </ThreadPrimitive.Messages>
                            </div>
                        </div>

                        <CompactionBanner />

                        <AuiIf condition={(s) => !s.thread.isEmpty}>
                            <div
                                aria-hidden="true"
                                className="shrink-0"
                                style={{
                                    height: spacerHeight
                                        ? `${spacerHeight}px`
                                        : "0px",
                                }}
                            />
                        </AuiIf>

                        <ThreadScrollToBottom />
                    </div>
                </ThreadPrimitive.Viewport>

                {activeCall && (
                    <div
                        ref={askUserRef}
                        className="absolute inset-x-0 bottom-0 z-50 bg-background"
                    >
                        <div className="mx-auto w-full max-w-(--thread-max-width) px-4 pb-3 pt-3">
                            <div className="max-h-[70vh] overflow-y-auto">
                                <AskUserTool
                                    {...(activeCall as React.ComponentProps<
                                        typeof AskUserTool
                                    >)}
                                />
                            </div>
                        </div>
                    </div>
                )}
                {pendingApproval && (
                    <div
                        ref={approvalRef}
                        className="absolute inset-x-0 bottom-0 z-50 bg-background"
                    >
                        <div className="mx-auto w-full max-w-(--thread-max-width) px-4 pb-3 pt-3">
                            <div className="max-h-[70vh] overflow-y-auto">
                                <ApprovalDialog />
                            </div>
                        </div>
                    </div>
                )}

                <ThreadComposerContainer
                    composer={composer}
                    modelSelection={modelSelection}
                    onHeightChange={setComposerHeight}
                    hidden={Boolean(activeCall || pendingApproval)}
                />
            </ThreadPrimitive.Root>
        </>
    );
};
