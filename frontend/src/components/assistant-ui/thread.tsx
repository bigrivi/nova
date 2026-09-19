import { ApprovalDialog } from "@/components/assistant-ui/approval-dialog";
import { AskUserTool } from "@/components/assistant-ui/ask-user-tool";
import { useZoom } from "@/lib/use-zoom";
import { useApprovalStore } from "@/stores/approval-store";
import { useAskUserStore } from "@/stores/ask-user-store";
import type { NovaAgent, NovaModelRecord } from "@/types/nova";
import { AuiIf, ThreadPrimitive } from "@assistant-ui/react";
import type { KeyboardEvent, RefObject } from "react";
import { type FC } from "react";

import { CompactionBanner } from "./thread-compaction-banner";
import { EmptyState } from "./thread-empty-state";
import { ThreadMessage } from "./thread-message";
import { ThreadScrollToBottom } from "./thread-scroll-to-bottom";
import { ThreadStickyComposer } from "./thread-sticky-composer";

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
        selectedModelId: string | null;
        onSelect: (modelId: string) => void;
    };
    agentSelection: {
        agents: NovaAgent[];
        selectedAgentKey: string | null;
        onSelect: (agentKey: string) => void;
    };
};

export const Thread: FC<ThreadProps> = ({
    composer,
    modelSelection,
    agentSelection,
}) => {
    const zoomTargetRef = useZoom();
    const activeCall = useAskUserStore((s) => s.active);
    const pendingApproval = useApprovalStore((s) => s.pending);

    // One composer, mounted either centered in the empty state or inside the
    // viewport footer. Only one branch is mounted at a time, so the draft and
    // textarea ref (both owned by the shell) survive the switch.
    const composerNode = (
        <ThreadStickyComposer
            composer={composer}
            modelSelection={modelSelection}
            agentSelection={agentSelection}
        />
    );
    const composerNodeWithDisclaimer = (
        <ThreadStickyComposer
            composer={composer}
            modelSelection={modelSelection}
            agentSelection={agentSelection}
            showDisclaimer
        />
    );

    return (
        <ThreadPrimitive.Root
            className="aui-root aui-thread-root @container relative flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-background"
            style={{
                ["--thread-max-width" as string]: "50rem",
                ["--composer-radius" as string]: "20px",
                ["--composer-padding" as string]: "10px",
            }}
        >
            <AuiIf condition={(s) => s.thread.isEmpty}>
                <EmptyState>{composerNode}</EmptyState>
            </AuiIf>

            <AuiIf condition={(s) => !s.thread.isEmpty}>
                <ThreadPrimitive.Viewport
                    autoScroll
                    data-slot="aui_thread-viewport"
                    turnAnchor="bottom"
                    className="relative flex min-h-0 flex-1 flex-col overflow-y-auto"
                >
                    {/* shrink-0 keeps min-h-full from collapsing this column to
                        the viewport height, which would make it a too-short
                        sticky containing block for the footer. */}
                    <div className="mx-auto flex min-h-full w-full max-w-(--thread-max-width) shrink-0 flex-col px-5 pt-6">
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

                        <ThreadPrimitive.ViewportFooter className="sticky bottom-0 z-20 mt-auto flex w-full flex-col">
                            <ThreadScrollToBottom />

                            {pendingApproval ? (
                                <div className="bg-background pb-3 pt-3">
                                    <div className="max-h-[70vh] overflow-y-auto">
                                        <ApprovalDialog />
                                    </div>
                                </div>
                            ) : activeCall ? (
                                <div className="bg-background pb-3 pt-3">
                                    <div className="max-h-[70vh] overflow-y-auto">
                                        <AskUserTool
                                            {...(activeCall as React.ComponentProps<
                                                typeof AskUserTool
                                            >)}
                                        />
                                    </div>
                                </div>
                            ) : (
                                composerNodeWithDisclaimer
                            )}
                        </ThreadPrimitive.ViewportFooter>
                    </div>
                </ThreadPrimitive.Viewport>
            </AuiIf>
        </ThreadPrimitive.Root>
    );
};
