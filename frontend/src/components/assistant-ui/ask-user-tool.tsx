"use client";

import type { ToolCallMessagePartComponent } from "@assistant-ui/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckIcon, ChevronLeftIcon, LoaderIcon, MessageSquareQuoteIcon } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// ── Types matching backend ──────────────────────────────────────────

type AskUserOption = {
  label: string;
  description: string;
};

type AskUserQuestion = {
  id: string;
  header: string;
  question: string;
  input_type: "text" | "select" | "confirm" | "textarea";
  options: AskUserOption[];
  multiple?: boolean;
  required?: boolean;
  default?: string;
};

// ── Payload parsers ─────────────────────────────────────────────────

function tryParseJson(raw: unknown): unknown {
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  return raw;
}

function normalizeQuestion(raw: Record<string, unknown>): AskUserQuestion | null {
  const question = String(raw.question ?? "").trim();
  if (!question) return null;

  const inputType = String(raw.input_type ?? "text").trim().toLowerCase();
  const options = Array.isArray(raw.options)
    ? raw.options
        .filter((o): o is Record<string, unknown> => !!o && typeof o === "object")
        .map((o) => ({
          label: String(o.label ?? "").trim(),
          description: String(o.description ?? "").trim(),
        }))
        .filter((o) => o.label)
    : [];

  const normalizedType: AskUserQuestion["input_type"] =
    inputType === "select" ? "select"
    : inputType === "confirm" ? "confirm"
    : inputType === "textarea" ? "textarea"
    : "text";

  return {
    id: String(raw.id ?? "").trim(),
    header: String(raw.header ?? "").trim(),
    question,
    input_type: normalizedType,
    options,
    multiple: Boolean(raw.multiple),
    required: raw.required !== false,
    default: String(raw.default ?? ""),
  };
}

function normalizeAskUserQuestions(value: unknown): AskUserQuestion[] | null {
  const parsed = tryParseJson(value);
  if (!parsed || typeof parsed !== "object") return null;

  const obj = parsed as Record<string, unknown>;
  if (!Array.isArray(obj.questions) || obj.questions.length === 0) return null;

  const result: AskUserQuestion[] = [];
  for (const q of obj.questions) {
    if (q && typeof q === "object") {
      const nq = normalizeQuestion(q as Record<string, unknown>);
      if (nq) result.push(nq);
    }
  }
  return result.length > 0 ? result : null;
}

// ── Component ───────────────────────────────────────────────────────

export const AskUserTool: ToolCallMessagePartComponent = (props) => {
  const { args, argsText, result, status, resume } = props;
  const { t } = useTranslation();

  const questions =
    normalizeAskUserQuestions(result) ??
    normalizeAskUserQuestions(args) ??
    normalizeAskUserQuestions(argsText);

  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    questions
      ? Object.fromEntries(
          questions
            .filter((q) => q.default)
            .map((q) => [q.id, q.default!]),
        )
      : {},
  );
  const [activeStep, setActiveStep] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  const isWizard = (questions?.length ?? 0) > 1;
  const isRunning = status?.type === "running";
  const confirmStep = questions ? questions.length : 0;
  const isReview = activeStep === confirmStep;

  const setAnswer = useCallback((id: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [id]: value }));
  }, []);

  const toggleMultiSelect = useCallback((id: string, label: string) => {
    setAnswers((prev) => {
      const current = prev[id] ? prev[id].split(", ").filter(Boolean) : [];
      const idx = current.indexOf(label);
      if (idx >= 0) {
        current.splice(idx, 1);
      } else {
        current.push(label);
      }
      return { ...prev, [id]: current.join(", ") };
    });
  }, []);

  const allRequiredFilled = useMemo(
    () => questions?.every((q) => !q.required || answers[q.id]) ?? false,
    [questions, answers],
  );

  const currentQuestion = isReview ? null : questions?.[activeStep] ?? null;

  const canAdvance = useMemo(() => {
    if (!currentQuestion) return true;
    if (!currentQuestion.required) return true;
    if (currentQuestion.input_type === "confirm") return true;
    if (currentQuestion.input_type === "select") {
      if (currentQuestion.multiple) {
        return Boolean(answers[currentQuestion.id]);
      }
      return currentQuestion.options.length > 0;
    }
    return Boolean(answers[currentQuestion.id]);
  }, [currentQuestion, answers]);

  // ── Tab value ──

  const tabValue = isReview ? "review" : `step-${activeStep}`;

  const handleTabChange = useCallback(
    (value: string) => {
      if (submitted) return;
      if (value === "review") {
        if (isReview || activeStep >= confirmStep - 1) {
          setActiveStep(confirmStep);
        }
        return;
      }
      const step = parseInt(value.replace("step-", ""), 10);
      if (step <= activeStep) {
        setActiveStep(step);
      }
    },
    [submitted, isReview, activeStep, confirmStep],
  );

  // ── Navigation ──

  const goNext = useCallback(() => {
    if (!questions) return;
    if (activeStep < questions.length - 1) {
      setActiveStep((s) => s + 1);
    } else {
      setActiveStep(confirmStep);
    }
  }, [activeStep, questions, confirmStep]);

  const goBack = useCallback(() => {
    if (activeStep > 0) setActiveStep((s) => s - 1);
  }, [activeStep]);

  const handleSubmit = useCallback(() => {
    if (!questions || submitted) return;
    const lines: string[] = [];
    for (const q of questions) {
      const answer = answers[q.id];
      lines.push(`Q (${q.id}): ${q.question}`);
      lines.push(`A: ${answer ?? ""}`);
      lines.push("");
    }
    const formatted = lines.join("\n").trim();
    if (formatted) {
      setSubmitted(true);
      resume?.(formatted);
    }
  }, [questions, answers, resume, submitted]);

  const handleCancel = useCallback(() => {
    if (!questions || submitted) return;
    const lines: string[] = [];
    for (const q of questions) {
      lines.push(`Q (${q.id}): ${q.question}`);
      lines.push(`A: [cancelled by user]`);
      lines.push("");
    }
    setSubmitted(true);
    resume?.(lines.join("\n").trim());
  }, [questions, resume, submitted]);

  useEffect(() => {
    if (submitted) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        handleCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleCancel, submitted]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (isWizard) {
          if (canAdvance) goNext();
        } else {
          if (currentQuestion?.required && !answers[currentQuestion.id]) return;
          handleSubmit();
        }
      }
    },
    [isWizard, canAdvance, goNext, handleSubmit, currentQuestion, answers],
  );

  // ── Guard ──

  if (!questions || questions.length === 0) return null;

  // ── Question input ──

  const renderInput = (q: AskUserQuestion, idx: number) => {
    const aid = q.id || `q${idx}`;
    const answer = answers[aid];

    return (
      <div key={aid} className="space-y-2">
        <div className="whitespace-pre-wrap text-sm font-medium leading-6 text-sky-950">
          {q.question}
        </div>

        {q.input_type === "confirm" ? (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAnswer(aid, "yes")}
              className={`rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
                answer === "yes"
                  ? "bg-sky-600 text-white"
                  : "border border-sky-200 bg-white/80 text-slate-700 hover:bg-sky-50"
              }`}
            >
              {t("tools.confirmYes")}
            </button>
            <button
              type="button"
              onClick={() => setAnswer(aid, "no")}
              className={`rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
                answer === "no"
                  ? "bg-sky-600 text-white"
                  : "border border-sky-200 bg-white/80 text-slate-700 hover:bg-sky-50"
              }`}
            >
              {t("tools.confirmNo")}
            </button>
          </div>
        ) : q.input_type === "select" ? (
          <div className="space-y-1">
            {q.options.map((opt) => {
              const isMulti = q.multiple;
              const selected = isMulti
                ? (answer ?? "").split(", ").includes(opt.label)
                : answer === opt.label;
              return (
                <button
                  key={opt.label}
                  type="button"
                  onClick={() => {
                    if (isMulti) {
                      toggleMultiSelect(aid, opt.label);
                    } else {
                      setAnswer(aid, opt.label);
                    }
                  }}
                  className={`w-full rounded-xl border px-3 py-2 text-left text-sm transition-colors ${
                    selected
                      ? "border-sky-400 bg-sky-100 text-sky-900"
                      : "border-sky-200 bg-white/80 text-slate-900 hover:bg-sky-50"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {isMulti ? (
                      <span className="size-4 shrink-0 text-sky-600">
                        {selected ? "☑" : "☐"}
                      </span>
                    ) : (
                      selected && <CheckIcon className="size-4 shrink-0 text-sky-600" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-medium">{opt.label}</div>
                      {opt.description ? (
                        <div className="mt-0.5 text-xs leading-5 text-slate-600">
                          {opt.description}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        ) : q.input_type === "textarea" ? (
          <textarea
            value={answer ?? ""}
            onChange={(e) => setAnswer(aid, e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("tools.answerPlaceholder")}
            rows={4}
            className="w-full min-h-[80px] rounded-xl border border-sky-200 bg-white/80 px-3 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-400 resize-y"
          />
        ) : (
          <input
            type="text"
            value={answer ?? ""}
            onChange={(e) => setAnswer(aid, e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("tools.answerPlaceholder")}
            className="w-full rounded-xl border border-sky-200 bg-white/80 px-3 py-2 text-sm text-slate-900 placeholder-slate-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-400"
          />
        )}

        {q.input_type === "select" && q.options.length > 0 && (
          <div className="text-xs text-sky-800">
            {q.multiple ? t("tools.selectMultiple") : t("tools.selectSingle")}
          </div>
        )}
      </div>
    );
  };

  // ── Review step ──

  const renderReview = () => (
    <div className="space-y-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-sky-700">
        {t("tools.review")}
      </div>
      {questions.map((q, i) => {
        const answer = answers[q.id || `q${i}`];
        return (
          <div key={q.id || i} className="space-y-0.5">
            <div className="text-sm font-medium text-sky-950">
              {q.header || q.question}
            </div>
            <div className="rounded-lg border border-sky-200 bg-white/80 px-3 py-2 text-sm text-slate-700">
              {answer || (q.required ? "(not answered)" : "(skipped)")}
            </div>
          </div>
        );
      })}
    </div>
  );

  // ── Submitted state ──

  if (submitted) {
    return (
      <div className="rounded-2xl border border-sky-200 bg-sky-50/80 px-4 py-4 text-sm text-sky-950">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-full bg-sky-100 p-2 text-sky-700">
            <CheckIcon className="size-4" />
          </div>
          <div className="min-w-0 flex-1 space-y-3">
            {questions.map((q, i) => {
              const aid = q.id || `q${i}`;
              return (
                <div key={aid} className="space-y-1">
                  {q.header ? (
                    <div className="text-xs font-semibold uppercase tracking-wide text-sky-700">
                      {q.header}
                    </div>
                  ) : null}
                  <div className="whitespace-pre-wrap text-sm font-medium leading-6 text-sky-950">
                    {q.question}
                  </div>
                  <div className="rounded-xl border border-sky-200 bg-white/80 px-3 py-2 text-sm text-slate-700">
                    {answers[aid] || (q.required ? "(not answered)" : "(skipped)")}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // ── Main render ──

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

        <div className="min-w-0 flex-1 space-y-4">
          {isWizard ? (
            <Tabs value={tabValue} onValueChange={handleTabChange}>
              <TabsList className="w-full justify-start gap-1 rounded-none border-b border-sky-200 bg-transparent p-0">
                {questions.map((q, i) => (
                  <TabsTrigger
                    key={q.id || i}
                    value={`step-${i}`}
                    disabled={i > activeStep || submitted}
                    className="relative rounded-none border-b-2 border-transparent px-2.5 py-1.5 text-xs font-medium data-[state=active]:border-sky-600 data-[state=active]:bg-transparent data-[state=active]:text-sky-700"
                  >
                    {q.header || `Step ${i + 1}`}
                    {answers[q.id || `q${i}`] && (
                      <CheckIcon className="ml-1 size-3 text-sky-500" />
                    )}
                  </TabsTrigger>
                ))}
                <TabsTrigger
                  value="review"
                  disabled={
                    submitted || (activeStep < questions.length - 1 && !isReview)
                  }
                  className="relative rounded-none border-b-2 border-transparent px-2.5 py-1.5 text-xs font-medium data-[state=active]:border-sky-600 data-[state=active]:bg-transparent data-[state=active]:text-sky-700"
                >
                  {t("tools.review")}
                </TabsTrigger>
              </TabsList>

              {questions.map((q, i) => (
                <TabsContent key={q.id || i} value={`step-${i}`} className="pt-2">
                  {renderInput(q, i)}
                  <div className="mt-4 flex items-center gap-2">
                    {activeStep > 0 && (
                      <button
                        type="button"
                        onClick={goBack}
                        className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium text-sky-700 transition-colors hover:bg-sky-100"
                      >
                        <ChevronLeftIcon className="size-4" />
                        {t("common.back")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        if (canAdvance) goNext();
                      }}
                      disabled={!canAdvance}
                      className="ml-auto rounded-lg bg-sky-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {t("common.next")}
                    </button>
                  </div>
                </TabsContent>
              ))}

              <TabsContent value="review" className="pt-2">
                {renderReview()}
                <div className="mt-4 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={goBack}
                    className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium text-sky-700 transition-colors hover:bg-sky-100"
                  >
                    <ChevronLeftIcon className="size-4" />
                    {t("common.back")}
                  </button>
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={!allRequiredFilled}
                    className="ml-auto rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {t("tools.submit")}
                  </button>
                  {!allRequiredFilled && (
                    <span className="text-xs text-sky-800">
                      {t("tools.requiredHint")}
                    </span>
                  )}
                </div>
              </TabsContent>
            </Tabs>
          ) : (
            <>
              {currentQuestion && renderInput(currentQuestion, activeStep)}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={
                    !!currentQuestion?.required && !answers[currentQuestion.id]
                  }
                  className="rounded-xl bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {t("tools.submit")}
                </button>
                {currentQuestion?.required && !answers[currentQuestion.id] && (
                  <span className="text-xs text-sky-800">
                    {t("tools.requiredHint")}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
