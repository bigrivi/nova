"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { memo, useMemo } from "react";

import {
  ToolFallbackContent,
  ToolFallbackError,
  ToolFallbackRoot,
  ToolFallbackTrigger,
} from "@/components/assistant-ui/tool-fallback";
import { cn } from "@/lib/utils";

type FileMutationViewModel = {
  displayName: string;
  headline: string;
  filePath: string | null;
  diff: string | null;
  plainResult: string | null;
};

function normalizeToolArgs(args: unknown, argsText?: string): Record<string, unknown> {
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
  return typeof filePath === "string" && filePath.trim() ? filePath.trim() : null;
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
  const diffPayload = resultText ? extractDiff(resultText) : { headline: "", diff: null };

  const verb = normalizedName === "edit" ? "Edited" : "Wrote";
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

const UnifiedDiffBlock = ({ diff }: { diff: string }) => {
  const lines = diff.split("\n");

  return (
    <div className="mx-4 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-inner">
      <div className="border-b border-slate-800 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        Unified Diff
      </div>
      <pre className="overflow-x-auto py-2 text-[12px] leading-6">
        {lines.map((line, index) => (
          <div
            key={`${index}:${line}`}
            className={cn(
              "px-4 font-mono whitespace-pre",
              getDiffLineClass(line),
            )}
          >
            {line || " "}
          </div>
        ))}
      </pre>
    </div>
  );
};

const FileMutationToolImpl: ToolCallMessagePartComponent = ({
  toolName,
  args,
  argsText,
  result,
  status,
}) => {
  const model = useMemo(
    () => buildViewModel(toolName, args, argsText, result),
    [args, argsText, result, toolName],
  );

  if (!model) {
    return null;
  }

  return (
    <ToolFallbackRoot className="border-emerald-200/70 bg-emerald-50/50">
      <ToolFallbackTrigger toolName={model.displayName} status={status} />
      <ToolFallbackContent>
        <ToolFallbackError status={status} />
        {model.filePath ? (
          <div className="px-4 text-xs font-medium text-emerald-900/80">
            {model.filePath}
          </div>
        ) : null}
        {model.headline ? (
          <p className="px-4 text-sm font-medium leading-6 text-slate-900">
            {model.headline}
          </p>
        ) : null}
        {model.diff ? (
          <UnifiedDiffBlock diff={model.diff} />
        ) : model.plainResult ? (
          <div className="px-4 pb-1">
            <pre className="whitespace-pre-wrap rounded-xl bg-white/80 px-3 py-3 text-[12px] leading-6 text-slate-700">
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
