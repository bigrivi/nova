/** Inline ask_user form.
 *
 * One question is shown at a time. With more than one question a tab bar
 * (titles from each question's header) sits above it; answering advances to
 * the next question automatically and the last answer submits. No outer frame
 * and no fixed height — the content flows downward. While a form is pending
 * the Composer is replaced (see App.tsx), so this owns all input.
 *
 * Supported shapes: text, textarea, single select, and multi select.
 */

import type {
    InputRenderable,
    KeyBinding,
    TextareaRenderable
} from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useRef, useState } from "react";
import type { AskQuestion } from "../stores/ask-user-store.ts";
import { theme } from "../theme.ts";

const ACCENT = theme.accent;
const MUTED = theme.muted;
const SURFACE = theme.surface

const FREEFORM_KEY_BINDINGS: KeyBinding[] = [
    { name: "enter", action: "submit" },
    { name: "enter", shift: true, action: "newline" },
];

export function AskUserCard({
    questions,
    onSubmit,
    onCancel,
}: {
    questions: AskQuestion[];
    onSubmit: (answers: Record<string, string>) => void;
    onCancel: () => void;
}) {
    const [active, setActive] = useState(0);
    const [answers, setAnswers] = useState<Record<string, string>>(() => {
        const seeded: Record<string, string> = {};
        for (const q of questions) {
            if (q.default) seeded[q.id] = q.default;
        }
        return seeded;
    });
    const [cursor, setCursor] = useState(0);
    const [draft, setDraft] = useState("");
    const inputRef = useRef<InputRenderable>(null);
    const textareaRef = useRef<TextareaRenderable>(null);

    const question = questions[active];
    const isLast = active === questions.length - 1;
    const isWizard = questions.length > 1;
    const isReview = isWizard && active === questions.length;
    const totalSteps = isWizard ? questions.length + 1 : questions.length;

    // Latest state for the global key handler without re-registering it on
    // every keystroke.
    const live = useRef({ question, answers, draft, active, cursor, isLast });
    live.current = { question, answers, draft, active, cursor, isLast };

    // Seed the active control (prefill defaults, restore a saved answer, place
    // the option cursor) whenever the active question changes.
    useEffect(() => {
        const q = questions[active];
        if (!q) return;
        const saved = answers[q.id] ?? "";
        if (q.inputType === "text") {
            const seed = saved || q.default || "";
            setDraft(seed);
            if (inputRef.current) inputRef.current.value = seed;
        } else if (q.inputType === "textarea") {
            const seed = saved || q.default || "";
            setDraft(seed);
            textareaRef.current?.setText(seed);
        } else if (q.inputType === "select") {
            const index = q.options.findIndex((o) => o.label === saved);
            setCursor(index >= 0 ? index : 0);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);



    function advance(merged: Record<string, string>): void {
        if (!isWizard) {
            onSubmit(merged);
            return;
        }
        if (live.current.active < questions.length - 1) {
            setCursor(0);
            setDraft("");
            setActive((index) => index + 1);
            return;
        }
        setActive(questions.length);
    }

    function submitReview(): void {
        const merged = live.current.answers;
        const allAnswered = questions.every(
            (q) => !q.required || (merged[q.id] ?? "").trim(),
        );
        if (allAnswered) {
            onSubmit(merged);
            return;
        }
        const firstMissing = questions.findIndex(
            (q) => q.required && !(merged[q.id] ?? "").trim(),
        );
        if (firstMissing >= 0) setActive(firstMissing);
    }

    function commit(value: string): void {
        const q = live.current.question;
        if (!q) return;
        if (!value.trim() && q.required) return;
        const merged = { ...live.current.answers, [q.id]: value };
        setAnswers(merged);
        advance(merged);
    }

    function toggleMulti(label: string): void {
        const q = live.current.question;
        if (!q || !label) return;
        const picked = (live.current.answers[q.id] ?? "")
            .split(", ")
            .filter(Boolean);
        const index = picked.indexOf(label);
        if (index >= 0) picked.splice(index, 1);
        else picked.push(label);
        setAnswers((prev) => ({ ...prev, [q.id]: picked.join(", ") }));
    }

    function moveCursor(delta: number): void {
        const q = live.current.question;
        if (!q) return;
        const size = q.options.length;
        setCursor((index) =>
            Math.min(Math.max(index + delta, 0), Math.max(size - 1, 0)),
        );
    }

    useKeyboard((key) => {
        if (key.name === "escape") {
            onCancel();
            return;
        }

        if (key.name === "tab" && isWizard) {
            setActive((index) => {
                const count = totalSteps;
                return key.shift
                    ? (index - 1 + count) % count
                    : (index + 1) % count;
            });
            return;
        }

        if (isReview) {
            if (key.name === "return" || key.name === "enter") {
                submitReview();
            }
            return;
        }

        const q = live.current.question;
        if (!q) return;

        if (q.inputType === "select") {
            if (key.name === "up") {
                moveCursor(-1);
                return;
            }
            if (key.name === "down") {
                moveCursor(1);
                return;
            }
            if (q.multiple && (key.name === "space" || key.name === " ")) {
                const option = q.options[live.current.cursor];
                if (option) toggleMulti(option.label);
                return;
            }
            if (key.name === "return" || key.name === "enter") {
                if (q.multiple) {
                    const picked = live.current.answers[q.id] ?? "";
                    if (!picked.trim() && q.required) return;
                    commit(picked);
                } else {
                    const option = q.options[live.current.cursor];
                    if (option) commit(option.label);
                }
            }
            return;
        }

    });

    if (!question && !isReview) return null;

    return (
        <box
            flexDirection="column"
            flexShrink={0}
            paddingX={2}
            paddingY={1}
            marginBottom={1}
            borderStyle="heavy"
            borderColor={ACCENT}
            border = {["left"]}
            backgroundColor={SURFACE}
            gap={0}
        >
            <box marginBottom={1} flexDirection="row" columnGap={2} flexShrink={0}>
                {isWizard && questions.map((q, index) => {
                    const label = q.header || `Q${index + 1}`;
                    if (index === active) {
                        return (
                            <box key={q.id} paddingX={1} backgroundColor={ACCENT}>
                                <text fg={SURFACE}>{label}</text>
                            </box>
                        );
                    }
                    return (
                        <box key={q.id} paddingX={1}>
                            <text>{label}</text>
                        </box>
                    );
                })}
                {isWizard ? (
                    isReview ? (
                        <box paddingX={1} backgroundColor={ACCENT}>
                            <text fg={SURFACE}>Confirm</text>
                        </box>
                    ) : (
                        <box paddingX={1}>
                            <text>Confirm</text>
                        </box>
                    )
                ) : null}
            </box>

            {isReview ? (
                <box flexDirection="column" flexShrink={0}>
                    <text fg={ACCENT}>Confirm</text>
                    {questions.map((q) => {
                        const answer = answers[q.id] ?? "";
                        return (
                            <box key={q.id} flexDirection="column" marginTop={1}>
                                <text fg={theme.foreground}>
                                    {q.header || q.question}
                                </text>
                                <text fg={MUTED}>
                                    {answer ||
                                        (q.required
                                            ? "(not answered)"
                                            : "(skipped)")}
                                </text>
                            </box>
                        );
                    })}
                </box>
            ) : question ? (
                <box flexDirection="column" flexShrink={0}>
                {!isWizard && question.header ? (
                    <text fg={ACCENT}>{question.header}</text>
                ) : null}
                <text fg={theme.foreground} content={question.question} />

                {question.inputType === "select" ? (
                    <box flexDirection="column" flexShrink={0} marginTop={1}>
                        {question.options.map((option, oi) => {
                            const picked = question.multiple
                                ? (answers[question.id] ?? "")
                                      .split(", ")
                                      .includes(option.label)
                                : answers[question.id] === option.label;
                            const pointed = oi === cursor;
                            const mark = question.multiple
                                ? picked
                                    ? "[x] "
                                    : "[ ] "
                                : picked
                                  ? "(•) "
                                  : "( ) ";
                            return (
                                <box
                                    key={option.label}
                                    flexDirection="row"
                                    flexShrink={0}
                                    columnGap={1}
                                >
                                    <text
                                        fg={pointed ? ACCENT : theme.foreground}
                                    >
                                        {pointed ? "▸ " : "  "}
                                        {mark}
                                        {option.label}
                                    </text>
                                    {option.description ? (
                                        <text fg={MUTED}>
                                            {option.description}
                                        </text>
                                    ) : null}
                                </box>
                            );
                        })}
                        <text fg={MUTED}>
                            {question.multiple
                                ? "↑↓ move · space toggle · enter confirm"
                                : "↑↓ move · enter select"}
                        </text>
                    </box>
                ) : null}

                {question.inputType === "text" ? (
                    <input
                        key={question.id}
                        ref={inputRef}
                        focused
                        marginTop={1}
                        placeholder="Your answer…"
                        placeholderColor={MUTED}
                        onInput={(value) => setDraft(value ?? "")}
                        onSubmit={() => commit(live.current.draft)}
                    />
                ) : null}

                {question.inputType === "textarea" ? (
                    <textarea
                        key={question.id}
                        ref={textareaRef}
                        focused
                        marginTop={1}
                        placeholder="Your answer… (enter submits, shift+enter newline)"
                        placeholderColor={MUTED}
                        keyBindings={FREEFORM_KEY_BINDINGS}
                        onContentChange={() =>
                            setDraft(textareaRef.current?.plainText ?? "")
                        }
                        onSubmit={() =>
                            commit(textareaRef.current?.plainText ?? "")
                        }
                    />
                ) : null}
                </box>
            ) : null}

            <text fg={MUTED} marginTop={1}>
                {active + 1}/{totalSteps} ·{" "}
                {isReview || (!isWizard && isLast)
                    ? "enter submits"
                    : "enter next"}
                {isWizard ? " · tab switch" : ""} · esc skip
            </text>
        </box>
    );
}
