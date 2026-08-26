/** Inline ask_user card: renders in the message flow, owns keyboard while active.
 *
 * Unlike the old floating dialog this does not cover the transcript, but it
 * still exclusively captures input: the Composer stays disabled until every
 * question is answered (text/textarea answers are typed inside the card).
 */

import { InputRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useRef, useState } from "react";
import type { AskQuestion } from "../stores/ask-user-store.ts";

import { theme } from "../theme.ts";

const ACCENT = theme.accent;
const MUTED = theme.muted;
const OPTION_IDLE = theme.subtle;

export function AskUserCard({
    questions,
    onSubmit,
    onCancel,
}: {
    questions: AskQuestion[];
    onSubmit: (answers: Record<string, string>) => void;
    onCancel: () => void;
}) {
    const [step, setStep] = useState(0);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [selected, setSelected] = useState(0);
    const [draft, setDraft] = useState("");
    const inputRef = useRef<InputRenderable>(null);

    const question = questions[step];
    const isLast = step === questions.length - 1;
    const freeform =
        question?.inputType === "text" || question?.inputType === "textarea";

    const live = useRef({ question, isLast, draft });
    live.current = { question, isLast, draft };

    // Free-form questions own a focused input inside the card; selection
    // questions keep focus here so arrows/enter work without a text field.
    useEffect(() => {
        if (!freeform) {
            inputRef.current?.blur();
        }
    }, [freeform, step]);

    useKeyboard((key) => {
        const q = live.current.question;
        if (!q) return;

        if (q.inputType === "select") {
            if (key.name === "up") {
                setSelected((index) => Math.max(0, index - 1));
                return;
            }
            if (key.name === "down") {
                setSelected((index) =>
                    Math.min(q.options.length - 1, index + 1),
                );
                return;
            }
        }

        if (q.inputType === "confirm") {
            if (key.name === "y") {
                answer("yes");
                return;
            }
            if (key.name === "n") {
                answer("no");
                return;
            }
        }

        // Enter submits: for select it picks the highlighted option, for
        // free-form it takes the in-card draft. Shift+enter inserts a newline
        // in textarea mode and is ignored here because opentui reports keyup
        // per physical key.
        if (key.name === "return" || key.name === "enter") {
            if (q.inputType === "select") {
                answer(q.options[selected]?.label ?? "");
            } else if (freeform && !key.shift) {
                answer(live.current.draft);
            }
            return;
        }

        if (key.name === "escape") {
            onCancel();
        }
    });

    function answer(value: string): void {
        const q = live.current.question;
        if (!q) return;
        if (!value.trim() && q.required) {
            return;
        }
        const merged = { ...answers, [q.id]: value };
        setAnswers(merged);
        setDraft("");
        if (live.current.isLast) {
            onSubmit(merged);
        } else {
            setSelected(0);
            setStep((current) => current + 1);
        }
    }

    function onDraftInput(value: string): void {
        setDraft(value ?? "");
    }

    if (!question) {
        return null;
    }

    return (
        <box
            flexDirection="column"
            border
            borderStyle="rounded"
            borderColor={ACCENT}
            paddingX={2}
            paddingY={1}
            marginBottom={1}
        >
            <text fg={ACCENT}>{question.header || "Nova asks"}</text>
            <text content={question.question} />

            {question.inputType === "select" ? (
                <box flexDirection="column" marginTop={1}>
                    {question.options.map((option, index) => (
                        <text
                            key={option.label}
                            fg={index === selected ? ACCENT : OPTION_IDLE}
                        >
                            {index === selected ? "▸ " : "  "}
                            {option.label}
                        </text>
                    ))}
                    <text fg={MUTED} marginTop={1}>
                        ↑↓ select · enter submit · esc skip
                    </text>
                </box>
            ) : null}

            {question?.inputType === "confirm" ? (
                <text fg={OPTION_IDLE} marginTop={1}>
                    y yes · n no · esc skip
                </text>
            ) : null}

            {question && freeform ? (
                <input
                    ref={inputRef}
                    flexGrow={1}
                    focused
                    marginTop={1}
                    placeholder={
                        question.inputType === "textarea"
                            ? "Your answer… (enter submits)"
                            : "Your answer…"
                    }
                    placeholderColor={MUTED}
                    onInput={onDraftInput}
                    onSubmit={() => answer(live.current.draft)}
                />
            ) : null}

            <text fg={MUTED} marginTop={1}>
                {step + 1}/{questions.length} •{" "}
                {isLast ? "enter submits" : "enter next"} • esc skip
            </text>
        </box>
    );
}
