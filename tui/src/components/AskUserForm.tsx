/** ask_user form dialog: answer questions one by one (text/select/confirm), submit answers as a new message to continue the stream */
import type { InputRenderable } from "@opentui/core";
import { useKeyboard } from "@opentui/react";
import { useRef, useState } from "react";
import { useAskUserStore, type AskQuestion } from "../stores/ask-user-store.ts";
import { formatAskAnswers, runChatStream } from "../stream/chat-stream.ts";

export function AskUserForm({ questions }: { questions: AskQuestion[] }) {
    const [step, setStep] = useState(0);
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [selected, setSelected] = useState(0);
    const inputRef = useRef<InputRenderable>(null);

    const question = questions[step];
    const isLast = step === questions.length - 1;

    const live = useRef({ question, isLast });
    live.current = { question, isLast };

    useKeyboard((key) => {
        const { question: q } = live.current;
        if (!q) return;
        if (q.inputType === "select") {
            if (key.name === "up") {
                setSelected((i) => Math.max(0, i - 1));
                return;
            }
            if (key.name === "down") {
                setSelected((i) => Math.min(q.options.length - 1, i + 1));
                return;
            }
            if (key.name === "enter") {
                answerAndAdvance(q.options[selected]?.label ?? "");
                return;
            }
        }
        if (q.inputType === "confirm") {
            if (key.name === "y" || (key.name === "enter" && !key.shift)) {
                answerAndAdvance("yes");
                return;
            }
            if (key.name === "n") {
                answerAndAdvance("no");
                return;
            }
        }
        if (key.name === "escape") {
            cancel();
        }
    });

    function answerAndAdvance(value: string): void {
        const q = live.current.question;
        if (!q) return;
        const merged = { ...answers, [q.id]: value };
        setAnswers(merged);
        if (live.current.isLast) {
            void finish(undefined, merged);
        } else {
            setSelected(0);
            setStep((s) => s + 1);
        }
    }

    function cancel(): void {
        void finish("[cancelled by user]", answers);
    }

    async function finish(
        override: string | undefined,
        mergedAnswers: Record<string, string>,
    ): Promise<void> {
        const finalAnswers =
            override !== undefined
                ? Object.fromEntries(questions.map((q) => [q.id, override]))
                : mergedAnswers;
        useAskUserStore.getState().setActive(null);
        const text = formatAskAnswers(questions, finalAnswers);
        if (text) {
            await runChatStream({ message: text });
        }
    }

    if (!question) {
        return null;
    }

    return (
        <box
            position="absolute"
            left="20%"
            right="20%"
            top="20%"
            paddingX={2}
            paddingY={2}
            border
            borderStyle="rounded"
            borderColor="#4f9cf9"
            backgroundColor="#0d1117"
        >
            <text fg="#4f9cf9">{question.header || "Nova asks"}</text>
            <text content={question.question} />
            {question.inputType === "text" ? (
                <input
                    ref={inputRef}
                    flexGrow={1}
                    focused
                    placeholder="Your answer…"
                    placeholderColor="#6e7681"
                    onSubmit={() => {
                        const value = inputRef.current?.value ?? "";
                        if (!value.trim() && question.required) return;
                        answerAndAdvance(value);
                    }}
                />
            ) : null}
            {question.inputType === "select" ? (
                <box flexDirection="column">
                    {question.options.map((option, index) => (
                        <text
                            key={option.label}
                            fg={index === selected ? "#4f9cf9" : "#8b949e"}
                        >
                            {index === selected ? "▸ " : "  "}
                            {option.label}
                        </text>
                    ))}
                </box>
            ) : null}
            {question.inputType === "confirm" ? (
                <text fg="#8b949e">[y] Yes [n] No</text>
            ) : null}
            <text fg="#6e7681">
                {step + 1}/{questions.length} •{" "}
                {isLast ? "enter submits" : "enter next"}
            </text>
        </box>
    );
}
