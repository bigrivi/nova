/** Inline ask_user form.
 *
 * Every question renders in one vertical flow so the content grows downward
 * with no fixed height and no outer frame. While a form is pending the
 * Composer is replaced (see App.tsx), so this owns all input.
 *
 * Supported shapes: text, textarea, single select, multi select, confirm.
 */

import type {
    InputRenderable,
    KeyBinding,
    TextareaRenderable,
} from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useEffect, useRef, useState } from "react";
import type { AskQuestion } from "../stores/ask-user-store.ts";
import { theme } from "../theme.ts";

const ACCENT = theme.accent;
const MUTED = theme.muted;

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
        } else if (q.inputType === "confirm") {
            setCursor(saved === "no" ? 1 : 0);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    function advance(merged: Record<string, string>): void {
        if (live.current.isLast) {
            onSubmit(merged);
        } else {
            setCursor(0);
            setDraft("");
            setActive((index) => index + 1);
        }
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
        const size = q.inputType === "confirm" ? 2 : q.options.length;
        setCursor((index) =>
            Math.min(Math.max(index + delta, 0), Math.max(size - 1, 0)),
        );
    }

    useKeyboard((key) => {
        const q = live.current.question;
        if (!q) return;

        if (key.name === "escape") {
            onCancel();
            return;
        }

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

        if (q.inputType === "confirm") {
            if (key.name === "y") {
                commit("yes");
                return;
            }
            if (key.name === "n") {
                commit("no");
                return;
            }
            if (key.name === "left") {
                setCursor(0);
                return;
            }
            if (key.name === "right") {
                setCursor(1);
                return;
            }
            if (key.name === "return" || key.name === "enter") {
                commit(live.current.cursor === 1 ? "no" : "yes");
            }
        }
    });

    if (!question) return null;

    return (
        <box flexDirection="column" flexShrink={0} paddingX={1} gap={0}>
            {questions.map((q, index) => {
                const isActive = index === active;
                const answer = answers[q.id] ?? "";
                return (
                    <box
                        key={q.id}
                        flexDirection="column"
                        flexShrink={0}
                        marginBottom={1}
                    >
                        {q.header ? (
                            <text fg={isActive ? ACCENT : MUTED}>
                                {q.header}
                            </text>
                        ) : null}
                        <text
                            fg={isActive ? theme.foreground : theme.subtle}
                            content={q.question}
                        />

                        {q.inputType === "select" ? (
                            <box flexDirection="column" flexShrink={0}>
                                {q.options.map((option, oi) => {
                                    const picked = q.multiple
                                        ? answer
                                              .split(", ")
                                              .includes(option.label)
                                        : answer === option.label;
                                    const pointed = isActive && oi === cursor;
                                    const mark = q.multiple
                                        ? picked
                                            ? "[x] "
                                            : "[ ] "
                                        : picked
                                          ? "(•) "
                                          : "( ) ";
                                    return (
                                        <box
                                            key={option.label}
                                            flexDirection="column"
                                            flexShrink={0}
                                        >
                                            <text
                                                fg={
                                                    pointed
                                                        ? ACCENT
                                                        : theme.foreground
                                                }
                                            >
                                                {pointed ? "▸ " : "  "}
                                                {mark}
                                                {option.label}
                                            </text>
                                            {option.description ? (
                                                <text fg={MUTED}>
                                                    {"    "}
                                                    {option.description}
                                                </text>
                                            ) : null}
                                        </box>
                                    );
                                })}
                                <text fg={MUTED}>
                                    {q.multiple
                                        ? "↑↓ move · space toggle · enter confirm"
                                        : "↑↓ move · enter select"}
                                </text>
                            </box>
                        ) : null}

                        {q.inputType === "confirm" ? (
                            <box flexDirection="column" flexShrink={0}>
                                <text
                                    fg={
                                        isActive && cursor === 0
                                            ? ACCENT
                                            : theme.foreground
                                    }
                                >
                                    {isActive && cursor === 0 ? "▸ " : "  "}
                                    [y] Yes
                                </text>
                                <text
                                    fg={
                                        isActive && cursor === 1
                                            ? ACCENT
                                            : theme.foreground
                                    }
                                >
                                    {isActive && cursor === 1 ? "▸ " : "  "}
                                    [n] No
                                </text>
                            </box>
                        ) : null}

                        {q.inputType === "text"
                            ? isActive
                                ? (
                                      <input
                                          key={q.id}
                                          ref={inputRef}
                                          focused
                                          placeholder="Your answer…"
                                          placeholderColor={MUTED}
                                          onInput={(value) =>
                                              setDraft(value ?? "")
                                          }
                                          onSubmit={() =>
                                              commit(live.current.draft)
                                          }
                                      />
                                  )
                                : (
                                      <text
                                          fg={answer ? theme.foreground : MUTED}
                                      >
                                          {answer || "(unanswered)"}
                                      </text>
                                  )
                            : null}

                        {q.inputType === "textarea"
                            ? isActive
                                ? (
                                      <textarea
                                          key={q.id}
                                          ref={textareaRef}
                                          focused
                                          placeholder="Your answer… (enter submits, shift+enter newline)"
                                          placeholderColor={MUTED}
                                          keyBindings={FREEFORM_KEY_BINDINGS}
                                          onContentChange={() =>
                                              setDraft(
                                                  textareaRef.current
                                                      ?.plainText ?? "",
                                              )
                                          }
                                          onSubmit={() =>
                                              commit(
                                                  textareaRef.current
                                                      ?.plainText ?? "",
                                              )
                                          }
                                      />
                                  )
                                : (
                                      <text
                                          fg={answer ? theme.foreground : MUTED}
                                      >
                                          {answer || "(unanswered)"}
                                      </text>
                                  )
                            : null}
                    </box>
                );
            })}
            <text fg={MUTED}>
                {active + 1}/{questions.length} ·{" "}
                {isLast ? "enter submits" : "enter next"} · esc skip
            </text>
        </box>
    );
}
