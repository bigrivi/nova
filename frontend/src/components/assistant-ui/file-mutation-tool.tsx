"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import type { TFunction } from "i18next";
import { memo, useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
    ToolFallbackContent,
    ToolFallbackError,
    ToolFallbackRoot,
    ToolFallbackTrigger,
} from "@/components/assistant-ui/tool-fallback";
import { errorTextFromResult } from "@/lib/tool-result";
import { cn } from "@/lib/utils";

type FileMutationViewModel = {
    displayName: string;
    headline: string;
    filePath: string | null;
    diff: string | null;
    plainResult: string | null;
};

function normalizeToolArgs(
    args: unknown,
    argsText?: string,
): Record<string, unknown> {
    if (args && typeof args === "object" && !Array.isArray(args)) {
        return args as Record<string, unknown>;
    }

    const text = String(argsText ?? "").trim();
    if (!text) {
        return {};
    }

    try {
        const parsed = JSON.parse(text);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : {};
    } catch {
        return {};
    }
}

function normalizeResultText(result: unknown): string | null {
    if (typeof result === "string") {
        const text = result.trim();
        return text || null;
    }

    if (!result || typeof result !== "object" || Array.isArray(result)) {
        return null;
    }

    const raw = result as Record<string, unknown>;
    const content = raw.content;
    if (typeof content === "string") {
        const text = content.trim();
        return text || null;
    }

    return null;
}

function getFilePath(args: Record<string, unknown>): string | null {
    const filePath = args.filePath;
    return typeof filePath === "string" && filePath.trim()
        ? filePath.trim()
        : null;
}

function getBaseName(filePath: string | null): string | null {
    if (!filePath) {
        return null;
    }

    const parts = filePath.split(/[/\\]/);
    return parts[parts.length - 1] || filePath;
}

function extractDiff(text: string): { headline: string; diff: string | null } {
    const divider = text.indexOf("\n\n--- ");
    if (divider < 0) {
        return {
            headline: text,
            diff: null,
        };
    }

    return {
        headline: text.slice(0, divider).trim(),
        diff: text.slice(divider + 2).trim(),
    };
}

function buildViewModel(
    t: TFunction,
    toolName: string,
    args: unknown,
    argsText: string | undefined,
    result: unknown,
): FileMutationViewModel | null {
    const normalizedName = toolName.trim().toLowerCase();
    if (normalizedName !== "edit" && normalizedName !== "write") {
        return null;
    }

    const normalizedArgs = normalizeToolArgs(args, argsText);
    const filePath = getFilePath(normalizedArgs);
    const baseName = getBaseName(filePath);
    const resultText = normalizeResultText(result);
    const diffPayload = resultText
        ? extractDiff(resultText)
        : { headline: "", diff: null };

    const verb =
        normalizedName === "edit" ? t("tools.edited") : t("tools.wrote");
    return {
        displayName: baseName ? `${verb} ${baseName}` : verb,
        headline: diffPayload.diff ? diffPayload.headline : "",
        filePath,
        diff: diffPayload.diff,
        plainResult: diffPayload.diff ? null : resultText,
    };
}

function getDiffLineClass(line: string): string {
    if (line.startsWith("--- ") || line.startsWith("+++ ")) {
        return "bg-sky-950/50 text-sky-200";
    }
    if (line.startsWith("@@")) {
        return "bg-amber-950/50 text-amber-200";
    }
    if (line.startsWith("+") && !line.startsWith("+++ ")) {
        return "bg-emerald-950/45 text-emerald-200";
    }
    if (line.startsWith("-") && !line.startsWith("--- ")) {
        return "bg-rose-950/45 text-rose-200";
    }
    return "text-slate-200";
}

function getLineType(line: string): "header" | "add" | "del" | "context" {
    if (
        line.startsWith("--- ") ||
        line.startsWith("+++ ") ||
        line.startsWith("@@")
    )
        return "header";
    if (line.startsWith("+") && !line.startsWith("+++ ")) return "add";
    if (line.startsWith("-") && !line.startsWith("--- ")) return "del";
    return "context";
}

type SplitRow = {
    left: string;
    right: string;
    leftClass: string;
    rightClass: string;
};

function parseSplitDiff(diff: string): SplitRow[] {
    const lines = diff.split("\n");
    const rows: SplitRow[] = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i];
        const lt = getLineType(line);
        if (lt === "header") {
            const cls = getDiffLineClass(line);
            rows.push({
                left: line,
                right: line,
                leftClass: cls,
                rightClass: cls,
            });
            i++;
        } else if (lt === "del") {
            if (i + 1 < lines.length && getLineType(lines[i + 1]) === "add") {
                rows.push({
                    left: line,
                    right: lines[i + 1],
                    leftClass: "bg-rose-950/45 text-rose-200",
                    rightClass: "bg-emerald-950/45 text-emerald-200",
                });
                i += 2;
            } else {
                rows.push({
                    left: line,
                    right: "",
                    leftClass: "bg-rose-950/45 text-rose-200",
                    rightClass: "text-slate-200",
                });
                i++;
            }
        } else if (lt === "add") {
            rows.push({
                left: "",
                right: line,
                leftClass: "text-slate-200",
                rightClass: "bg-emerald-950/45 text-emerald-200",
            });
            i++;
        } else {
            const cls = "text-slate-200";
            rows.push({
                left: line || " ",
                right: line || " ",
                leftClass: cls,
                rightClass: cls,
            });
            i++;
        }
    }
    return rows;
}

const SplitDiffBlock = ({ diff }: { diff: string }) => {
    const { t } = useTranslation();
    const rows = useMemo(() => parseSplitDiff(diff), [diff]);

    return (
        <div className="max-w-full overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-inner">
            <div className="grid grid-cols-2 divide-x divide-slate-700 max-[520px]:grid-cols-1 max-[520px]:divide-x-0 max-[520px]:divide-y">
                <div className="border-b border-slate-800 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    {t("tools.original")}
                </div>
                <div className="border-b border-slate-800 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    {t("tools.modified")}
                </div>
            </div>
            <div className="grid grid-cols-2 divide-x divide-slate-700 max-[520px]:grid-cols-1 max-[520px]:divide-x-0 max-[520px]:divide-y">
                <div className="min-w-0 overflow-x-auto py-2 text-[12px] font-mono leading-6">
                    {rows.map((row, i) => (
                        <div
                            key={i}
                            className={cn(
                                "px-4 whitespace-pre-wrap break-all min-[520px]:whitespace-pre min-[520px]:break-normal",
                                row.leftClass,
                            )}
                        >
                            {row.left || " "}
                        </div>
                    ))}
                </div>
                <div className="min-w-0 overflow-x-auto py-2 text-[12px] font-mono leading-6">
                    {rows.map((row, i) => (
                        <div
                            key={i}
                            className={cn(
                                "px-4 whitespace-pre-wrap break-all min-[520px]:whitespace-pre min-[520px]:break-normal",
                                row.rightClass,
                            )}
                        >
                            {row.right || " "}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

const FileMutationToolImpl: ToolCallMessagePartComponent = ({
    toolName,
    args,
    argsText,
    result,
    status,
    isError,
}) => {
    const { t } = useTranslation();
    const model = useMemo(
        () => buildViewModel(t, toolName, args, argsText, result),
        [args, argsText, result, toolName, t],
    );

    if (!model) {
        return null;
    }

    const errored = isError === true;

    return (
        <ToolFallbackRoot className={cn(errored && "opacity-80")}>
            <ToolFallbackTrigger
                toolName={model.displayName}
                argsText={argsText}
                status={status}
                isError={isError}
            />
            <ToolFallbackContent>
                <ToolFallbackError
                    status={status}
                    message={errored ? errorTextFromResult(result) : null}
                />
                {model.filePath ? (
                    <div className="font-mono text-xs font-medium text-[#1D5FA8]">
                        {model.filePath}
                    </div>
                ) : null}
                {errored ? null : model.headline ? (
                    <p className="font-sans text-sm font-medium leading-6 text-slate-900">
                        {model.headline}
                    </p>
                ) : null}
                {errored ? null : model.diff ? (
                    <SplitDiffBlock diff={model.diff} />
                ) : model.plainResult ? (
                    <div className="pb-1">
                        <pre className="whitespace-pre-wrap rounded-xl bg-white px-3 py-3 text-[12px] leading-6 text-slate-700">
                            {model.plainResult}
                        </pre>
                    </div>
                ) : null}
            </ToolFallbackContent>
        </ToolFallbackRoot>
    );
};

export const FileMutationTool = memo(
    FileMutationToolImpl,
) as ToolCallMessagePartComponent;
