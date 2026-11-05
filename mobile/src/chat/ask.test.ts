import { describe, expect, test } from "bun:test";

import {
    cancelAskText,
    formatAskAnswers,
    isAnswerComplete,
    parseAskQuestions,
} from "./ask";

describe("ask questions", () => {
    test("parses a list of text and select questions", () => {
        const questions = parseAskQuestions({
            questions: [
                {
                    id: "where",
                    header: "Location",
                    question: "Where are you?",
                    input_type: "text",
                    default: "home",
                },
                {
                    id: "when",
                    header: "Time",
                    question: "Which slot?",
                    input_type: "select",
                    options: [
                        { label: "Morning", value: "am" },
                        { label: "Evening", description: "after 6" },
                    ],
                    multiple: true,
                    required: false,
                },
            ],
        });
        expect(questions).toHaveLength(2);
        expect(questions[0]).toMatchObject({
            id: "where",
            inputType: "text",
            default: "home",
            required: true,
        });
        expect(questions[1]).toMatchObject({
            id: "when",
            inputType: "select",
            multiple: true,
            required: false,
        });
        expect(questions[1]!.options).toEqual([
            { label: "Morning", value: "am", description: "" },
            { label: "Evening", description: "after 6" },
        ]);
    });

    test("a single question object is accepted", () => {
        expect(
            parseAskQuestions({ question: { id: "q", question: "Why?" } }),
        ).toHaveLength(1);
    });

    test("malformed input yields no questions", () => {
        expect(parseAskQuestions(null)).toEqual([]);
        expect(parseAskQuestions("x")).toEqual([]);
        expect(parseAskQuestions({ questions: "x" })).toEqual([]);
    });

    test("formats answers the way the server expects", () => {
        const questions = parseAskQuestions({
            questions: [
                { id: "a", question: "First?" },
                { id: "b", question: "Second?" },
            ],
        });
        expect(
            formatAskAnswers(questions, { a: "one", b: "two" }),
        ).toBe(
            "Q (a): First?\nA: one\n\nQ (b): Second?\nA: two",
        );
    });

    test("cancellation and completeness", () => {
        const questions = parseAskQuestions({
            questions: [
                { id: "a", question: "First?" },
                { id: "b", question: "Second?", required: false },
            ],
        });
        expect(cancelAskText(questions)).toBe(
            "Q (a): [cancelled by user]\nQ (b): [cancelled by user]",
        );
        expect(isAnswerComplete(questions, { a: "yes" })).toBe(true);
        expect(isAnswerComplete(questions, { a: "  " })).toBe(false);
    });
});
