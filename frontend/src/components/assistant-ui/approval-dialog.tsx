"use client";

import { ShieldAlertIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { approveCommand } from "@/lib/nova-api";
import { useApprovalStore } from "@/stores/approval-store";

/**
 * File tools whose approval is about a directory, keyed by the verb the
 * dialog uses for them. The directory block shows the backend `family` field
 * -- the scope remembering would cover -- not the single target file path.
 * Tools missing here (e.g. web_fetch) keep the legacy tool-call copy below.
 */
const DIR_VERB_KEYS = {
    write: "approval.verbWrite",
    edit: "approval.verbWrite",
    read: "approval.verbRead",
    read_image: "approval.verbRead",
    grep: "approval.verbRead",
    glob: "approval.verbRead",
} as const;

export type ApprovalDirVerbKey =
    (typeof DIR_VERB_KEYS)[keyof typeof DIR_VERB_KEYS];

/** The verb key for a directory approval, or null to keep the legacy copy. */
export function approvalDirVerbKey(
    toolName: string,
): ApprovalDirVerbKey | null {
    const name = toolName.trim().toLowerCase();
    return (DIR_VERB_KEYS as Record<string, ApprovalDirVerbKey>)[name] ?? null;
}

export const ApprovalDialog = () => {
    const pending = useApprovalStore((s) => s.pending);
    const { t } = useTranslation();

    if (!pending) return null;

    // A tool-axis approval is not a shell line. The server sends toolName on both
    // axes, and `{"tools": {"web_fetch": "ask"}}` genuinely reaches this dialog --
    // labelling it "Shell Command" with the tool name in the code block told the
    // user nothing about what they were authorising.
    const isShell = !pending.toolName || pending.toolName === "shell";
    // grep/glob search a directory (their path arg is the directory to search
    // in), so they get a search title by tool name -- the frame carries no
    // "is a directory" field to guess from.
    const toolName = pending.toolName.trim().toLowerCase();
    const isSearch = toolName === "grep" || toolName === "glob";
    const verbKey = isShell ? null : approvalDirVerbKey(pending.toolName);
    // One verb variable feeds both the title and the explainer line, so the
    // two can never disagree about whether this is a read or a write.
    const verb = verbKey ? t(verbKey) : "";
    const isDir = verbKey !== null;

    const title = isShell
        ? t("approval.needShell")
        : isSearch
          ? t("approval.needSearch")
          : !isDir
            ? t("approval.toolTitle", { tool: pending.toolName })
            : pending.family
              ? t("approval.needDirAccess", { verb })
              : t("approval.needFileAccess", { verb });
    const block = isShell
        ? pending.command
        : isDir
          ? pending.family || pending.target
          : null;

    const handleApprove = async (remember: boolean) => {
        await approveCommand({
            sessionId: pending.sessionId,
            requestId: pending.requestId,
            approved: true,
            remember,
        });
        // Clear the per-session entry too, or syncPendingToSession would
        // restore this same prompt the next time the thread is opened.
        useApprovalStore.getState().clearPendingForSession(pending.sessionId);
    };

    const handleReject = async () => {
        await approveCommand({
            sessionId: pending.sessionId,
            requestId: pending.requestId,
            approved: false,
        });
        useApprovalStore.getState().clearPendingForSession(pending.sessionId);
    };

    return (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-4 text-sm text-amber-950">
            <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700">
                    <ShieldAlertIcon className="size-4" />
                </div>
                <div className="min-w-0 flex-1 space-y-3">
                    <div className="text-sm font-bold text-amber-950">
                        {title}
                    </div>
                    {/*
                     * The description and the command are the same string for a
                     * tool approval, so rendering both would print the tool's
                     * doc twice.
                     */}
                    {pending.description &&
                        pending.description !== pending.command && (
                            <div className="whitespace-pre-wrap text-sm leading-6">
                                {pending.description}
                            </div>
                        )}
                    {block && (
                        <pre className="overflow-x-auto rounded-xl border border-amber-200 bg-amber-100/70 px-3 py-2 font-mono text-xs whitespace-pre-wrap break-all text-amber-950">
                            {block}
                        </pre>
                    )}

                    {isShell && pending.workspace && (
                        <div className="font-mono text-xs text-amber-800">
                            {t("approval.workdir", { path: pending.workspace })}
                        </div>
                    )}
                    {(isShell || isDir) && (
                        <div className="text-xs leading-5 text-amber-800">
                            {isShell
                                ? t("approval.shellDiff")
                                : t("approval.dirDiff", { verb })}
                        </div>
                    )}
                    <div className="flex flex-wrap items-center gap-2">
                        <button
                            type="button"
                            onClick={() => handleApprove(false)}
                            className="rounded-xl bg-amber-950 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-900"
                        >
                            {t("approval.approve")}
                        </button>
                        {pending.rememberable && (
                            <button
                                type="button"
                                onClick={() => handleApprove(true)}
                                className="rounded-xl border border-amber-800 bg-transparent px-4 py-2 text-sm font-medium text-amber-950 transition-colors hover:bg-amber-100"
                            >
                                {t("approval.remember")}
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={handleReject}
                            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100"
                        >
                            {t("approval.reject")}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
