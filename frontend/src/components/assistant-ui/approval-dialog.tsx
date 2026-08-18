"use client";

import { ShieldAlertIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { approveCommand } from "@/lib/nova-api";
import { useApprovalStore } from "@/stores/approval-store";

export const ApprovalDialog = () => {
    const pending = useApprovalStore((s) => s.pending);
    const { t } = useTranslation();

    if (!pending) return null;

    const handleApprove = async (remember: boolean) => {
        await approveCommand({
            sessionId: pending.sessionId,
            requestId: pending.requestId,
            approved: true,
            remember,
        });
        useApprovalStore.getState().setPending(null);
    };

    const handleReject = async () => {
        await approveCommand({
            sessionId: pending.sessionId,
            requestId: pending.requestId,
            approved: false,
        });
        useApprovalStore.getState().setPending(null);
    };

    return (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-4 text-sm text-amber-950">
            <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700">
                    <ShieldAlertIcon className="size-4" />
                </div>
                <div className="min-w-0 flex-1 space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                        {t("approval.title")}
                    </div>
                    {pending.description && (
                        <div className="whitespace-pre-wrap text-sm leading-6">
                            {pending.description}
                        </div>
                    )}
                    <pre className="overflow-x-auto rounded-xl border border-amber-200 bg-white/80 px-3 py-2 text-xs text-slate-700">
                        {pending.command}
                    </pre>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={() => handleApprove(false)}
                            className="rounded-xl bg-amber-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-700"
                        >
                            {t("approval.approve")}
                        </button>
                        <button
                            type="button"
                            onClick={() => handleApprove(true)}
                            className="rounded-xl border border-amber-300 bg-white/80 px-4 py-2 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-100"
                        >
                            {t("approval.remember")}
                        </button>
                        <button
                            type="button"
                            onClick={handleReject}
                            className="rounded-xl border border-slate-300 bg-white/80 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100"
                        >
                            {t("approval.reject")}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
