"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { LoaderIcon, MessageSquareQuoteIcon } from "lucide-react";

type AskUserOption = {
  label: string;
  description: string;
};

type AskUserQuestion = {
  header: string;
  question: string;
  input_type: "text" | "select";
  options: AskUserOption[];
  multiple?: boolean;
};

function normalizeAskUserQuestion(value: unknown): AskUserQuestion | null {
  let candidate = value;

  if (typeof candidate === "string") {
    const text = candidate.trim();
    if (!text) {
      return null;
    }
    try {
      candidate = JSON.parse(text);
    } catch {
      return null;
    }
  }

  candidate =
    candidate && typeof candidate === "object" && "question" in candidate
      ? (candidate as { question?: unknown }).question
      : candidate;

  if (!candidate || typeof candidate !== "object") {
    return null;
  }

  const raw = candidate as Record<string, unknown>;
  const question = String(raw.question ?? "").trim();
  if (!question) {
    return null;
  }

  const inputType = String(raw.input_type ?? "text").trim().toLowerCase();
  const options = Array.isArray(raw.options)
    ? raw.options
        .filter((option): option is Record<string, unknown> => !!option && typeof option === "object")
        .map((option) => ({
          label: String(option.label ?? "").trim(),
          description: String(option.description ?? "").trim(),
        }))
        .filter((option) => option.label)
    : [];

  return {
    header: String(raw.header ?? "").trim(),
    question,
    input_type: inputType === "select" ? "select" : "text",
    options,
    multiple: Boolean(raw.multiple),
  };
}

export const AskUserTool: ToolCallMessagePartComponent = ({
  args,
  argsText,
  result,
  status,
}) => {
  const question =
    normalizeAskUserQuestion(result) ??
    normalizeAskUserQuestion(args) ??
    normalizeAskUserQuestion(argsText);
  const isRunning = status?.type === "running";

  if (!question) {
    return null;
  }

  return (
    <div className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-4 text-sm text-sky-950">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-sky-100 p-2 text-sky-700">
          {isRunning ? (
            <LoaderIcon className="size-4 animate-spin" />
          ) : (
            <MessageSquareQuoteIcon className="size-4" />
          )}
        </div>

        <div className="min-w-0 flex-1 space-y-3">
          <div className="space-y-1">
            {question.header ? (
              <div className="text-xs font-semibold uppercase tracking-wide text-sky-700">
                {question.header}
              </div>
            ) : null}
            <div className="whitespace-pre-wrap text-sm font-medium leading-6 text-sky-950">
              {question.question}
            </div>
          </div>

          {question.input_type === "select" && question.options.length > 0 ? (
            <div className="space-y-2">
              {question.options.map((option) => (
                <div
                  key={`${option.label}:${option.description}`}
                  className="rounded-xl border border-sky-200 bg-white/80 px-3 py-2"
                >
                  <div className="font-medium text-slate-900">{option.label}</div>
                  {option.description ? (
                    <div className="mt-1 text-xs leading-5 text-slate-600">
                      {option.description}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}

          <div className="text-xs leading-5 text-sky-800">
            {question.input_type === "select"
              ? question.multiple
                ? "Please answer below with all selected options."
                : "Please answer below with your selected option."
              : "Please answer below in the composer to continue."}
          </div>
        </div>
      </div>
    </div>
  );
};
