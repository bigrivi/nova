/** `ask_user` questions and the text form the server expects as the answer.
 *
 *  The tool returns its questions on `tool-input-available`; the turn then ends
 *  with `data-nova-input-required`. Answering starts a new turn whose message is
 *  the `Q (...)` / `A: ...` block below, which is exactly what the TUI sends.
 */

export type AskOption = {
    label: string;
    value?: string;
    description?: string;
};

export type AskQuestion = {
    id: string;
    header: string;
    question: string;
    inputType: "text" | "textarea" | "select";
    options: AskOption[];
    multiple: boolean;
    required: boolean;
    default: string;
};

export function parseAskQuestions(input: unknown): AskQuestion[] {
    if (!input || typeof input !== "object") {
        return [];
    }
    const record = input as Record<string, unknown>;
    const raw = Array.isArray(record.questions)
        ? record.questions
        : record.question;
    const list = Array.isArray(raw) ? raw : raw != null ? [raw] : [];
    const questions: AskQuestion[] = [];

    list.forEach((value, index) => {
        if (!value || typeof value !== "object") {
            return;
        }
        const item = value as Record<string, unknown>;
        const inputType = String(item.input_type ?? "text").toLowerCase();
        const options = Array.isArray(item.options)
            ? item.options
                  .filter(
                      (option): option is Record<string, unknown> =>
                          !!option && typeof option === "object",
                  )
                  .map((option) => ({
                      label: String(option.label ?? option.value ?? "").trim(),
                      ...(option.value !== undefined
                          ? { value: String(option.value) }
                          : {}),
                      description: String(option.description ?? "").trim(),
                  }))
                  .filter((option) => option.label)
            : [];

        questions.push({
            id: String(item.id ?? `q${index}`).trim() || `q${index}`,
            header: String(item.header ?? "").trim(),
            question: String(item.question ?? "").trim(),
            inputType:
                inputType === "select"
                    ? "select"
                    : inputType === "textarea"
                      ? "textarea"
                      : "text",
            options,
            multiple: Boolean(item.multiple),
            required: item.required !== false,
            default: String(item.default ?? ""),
        });
    });

    return questions;
}

export function formatAskAnswers(
    questions: readonly AskQuestion[],
    answers: Readonly<Record<string, string>>,
): string {
    return questions
        .map((question) => {
            return [
                `Q (${question.id}): ${question.question}`,
                `A: ${answers[question.id] ?? ""}`,
                "",
            ].join("\n");
        })
        .join("\n")
        .trim();
}

export function cancelAskText(questions: readonly AskQuestion[]): string {
    const text = questions
        .map((question) => `Q (${question.id}): [cancelled by user]`)
        .join("\n");
    return text || "[cancelled by user]";
}

export function isAnswerComplete(
    questions: readonly AskQuestion[],
    answers: Readonly<Record<string, string>>,
): boolean {
    return questions.every(
        (question) =>
            !question.required || (answers[question.id] ?? "").trim() !== "",
    );
}
